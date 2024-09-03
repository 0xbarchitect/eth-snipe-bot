import asyncio
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from time import time
from asgiref.sync import sync_to_async

import sys # for testing
sys.path.append('..')

from library import Singleton
from data import ReportData, ReportDataType, BlockData, Position, Pair, ExecutionAck, ControlOrder, ControlOrderType
from helpers import constants, get_hour_in_vntz

import django
from django.utils.timezone import make_aware
from django.db.models import Sum
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")
django.setup()

from console.models import Block, Transaction, PositionTransaction, BlackList
import console.models

BUY_AMOUNT=float(os.environ.get('BUY_AMOUNT'))
GAS_COST=float(os.environ.get('GAS_COST_GWEI'))*10**-9

class Reporter(metaclass=Singleton):
    def __init__(self, receiver, sender):
        self.receiver = receiver
        self.sender = sender

    async def run(self):
        await asyncio.gather(
            self.bootstrap(),
            self.listen_report(),
        )

    async def bootstrap(self):
        @sync_to_async
        def get_pending_positions():
            # fetch all pending positions
            pending_positions = []
            for pos in console.models.Position.objects.filter(is_liquidated=0, is_deleted=0).filter(purchased_at__gte=make_aware(datetime.now()-timedelta(hours=1))).all():
                pending_positions.append(Position(
                    pair=Pair(
                        address=pos.pair.address,
                        token=pos.pair.token,
                        token_index=pos.pair.token_index,
                        reserve_token=pos.pair.reserve_token,
                        reserve_eth=pos.pair.reserve_eth,
                        creator=pos.pair.creator,                        
                    ),
                    amount=pos.amount,
                    amount_in=pos.investment,
                    signer=pos.signer,
                    bot=pos.bot,
                    start_time=int(round(pos.purchased_at.timestamp()-10*60)), # TODO: shift start-time backward to force liquidate immediately
                    buy_price=pos.buy_price,
                ))
            return pending_positions

        pending_positions=await get_pending_positions()
        if len(pending_positions)>0:
            logging.warning(f"REPORTER Bootstrap pending positions with length {len(pending_positions)}")
            self.sender.put(ControlOrder(
                type=ControlOrderType.PENDING_POSITIONS,
                data=pending_positions,
            ))

    async def listen_report(self):
        logging.warning(f"REPORTER listen for report...")
        while True:
            report = await self.receiver.coro_get()
            logging.warning(f"REPORTER receive {report}")

            await self.save_to_db(report)

    async def save_to_db(self, report):
        async def save_block(report):
            block = await Block.objects.filter(block_number=report.data.block_number).afirst()
            if block is None:
                block = Block(
                    block_number=report.data.block_number,
                    block_timestamp=report.data.block_timestamp,
                    base_fee=report.data.base_fee,
                    gas_used=report.data.gas_used,
                    gas_limit=report.data.gas_limit,
                )
                await block.asave()
                logging.debug(f"block saved successfully {block.id}")
            else:
                logging.debug(f"block found id #{block.id}")

            for pair in report.data.pairs:
                pair_ins = await console.models.Pair.objects.filter(address=pair.address.lower()).afirst()
                if pair_ins is None:
                    pair_ins = console.models.Pair(
                        address=pair.address.lower(),
                        token=pair.token.lower(),
                        token_index=pair.token_index,
                        reserve_token=pair.reserve_token,
                        reserve_eth=pair.reserve_eth,
                        deployed_at=make_aware(datetime.fromtimestamp(report.data.block_timestamp)),
                        creator=pair.creator.lower() if pair.creator is not None else None,
                        deployed_block=report.data.block_number,
                    )
                    await pair_ins.asave()
                    logging.debug(f"pair saved with id #{pair_ins.id}")
                else:
                    logging.debug(f"pair exists id #{pair_ins.id}")

        async def update_pnl(position: console.models.Position):
            async def determine_number_position(day_obj: datetime):
                day_str = day_obj.strftime('%Y-%m-%d')
                hour_str = day_obj.strftime('%H')
                return await console.models.Position.objects.filter(purchased_at__date=day_str, purchased_at__hour=hour_str).acount()
            
            async def determine_number_failed(day_obj: datetime):
                day_str = day_obj.strftime('%Y-%m-%d')
                hour_str = day_obj.strftime('%H')
                return await console.models.Position.objects.filter(purchased_at__date=day_str, purchased_at__hour=hour_str, pnl__lte=-100).acount()
            
            async def calculate_hourly_pnl(day_obj: datetime):
                day_str = day_obj.strftime('%Y-%m-%d')
                hour_str = day_obj.strftime('%H')
                sum = await console.models.Position.objects.filter(purchased_at__date=day_str, purchased_at__hour=hour_str).aaggregate(Sum('pnl'))
                return Decimal(sum['pnl__sum'])

            async def calculate_avg_daily_pnl(day_obj: datetime):
                day_str = day_obj.strftime('%Y-%m-%d')
                sum = await console.models.Position.objects.filter(purchased_at__date=day_str).aaggregate(Sum('pnl'))
                hour_elapsed = int(day_obj.strftime('%H'))+1
                return Decimal(sum['pnl__sum']/hour_elapsed)

            timestamp = position.created_at.strftime('%Y-%m-%d %H:00:00')
            pnl = await console.models.PnL.objects.filter(timestamp=timestamp).afirst()
            if pnl is None:
                pnl = console.models.PnL(
                    timestamp=timestamp,
                    number_positions=await determine_number_position(position.created_at),
                    hourly_pnl=await calculate_hourly_pnl(position.created_at),
                    avg_daily_pnl=await calculate_avg_daily_pnl(position.created_at),
                    number_failed=await determine_number_failed(position.created_at),
                )

                await pnl.asave()
                logging.info(f"REPORTER Create new PnL #{pnl.id}")
            else:
                if position.is_liquidated==1:
                    pnl.hourly_pnl=await calculate_hourly_pnl(position.created_at)
                    pnl.avg_daily_pnl=await calculate_avg_daily_pnl(position.created_at)
                    pnl.number_failed=await determine_number_failed(position.created_at)
                else:
                    pnl.number_positions=await determine_number_position(position.created_at)

                await pnl.asave()
                logging.info(f"REPORTER Update existing PnL #{pnl.id}")

        async def save_position(execution_ack: ExecutionAck):
            block = await Block.objects.filter(block_number=execution_ack.block_number).afirst()
            if block is None:
                block = Block(
                    block_number=execution_ack.block_number,
                )
                await block.asave()
                logging.debug(f"block saved successfully {block.id}")
            else:
                logging.debug(f"block found id #{block.id}")

            tx = await Transaction.objects.filter(tx_hash=execution_ack.tx_hash).afirst()
            if tx is None:
                tx = Transaction(
                    block=block,
                    tx_hash=execution_ack.tx_hash,
                    status=execution_ack.tx_status,
                )
                await tx.asave()
                logging.debug(f"tx saved id #{tx.id}")
            else:
                logging.debug(f"tx exists id #{tx.id}")

            pair = await console.models.Pair.objects.filter(address=execution_ack.pair.address.lower(),token=execution_ack.pair.token.lower()).afirst()
            if pair is None:
                pair = console.models.Pair(
                    address=execution_ack.pair.address.lower(),
                    token=execution_ack.pair.token.lower(),
                )
                await pair.asave()
                logging.debug(f"pair saved id #{pair.id}")
            else:
                logging.debug(f"pair exists id #{pair.id}")

            position = await console.models.Position.objects.filter(pair__address=execution_ack.pair.address.lower(), is_deleted=0).afirst()
            if position is None:
                position = console.models.Position(
                    pair=pair,
                    amount=execution_ack.amount_out if execution_ack.is_buy else 0,
                    buy_price=Decimal(execution_ack.amount_in)/Decimal(execution_ack.amount_out) if execution_ack.amount_out>0 and execution_ack.is_buy else 0,
                    purchased_at=make_aware(datetime.fromtimestamp(int(time()))),
                    is_liquidated=0 if execution_ack.is_buy else 1,
                    sell_price=Decimal(execution_ack.amount_out)/Decimal(execution_ack.amount_in) if execution_ack.amount_in>0 and not execution_ack.is_buy else 0,
                    liquidation_attempts=0,
                    pnl=0,
                    signer=execution_ack.signer.lower() if execution_ack.signer is not None else None,
                    bot=execution_ack.bot.lower() if execution_ack.bot is not None else None,
                    investment=Decimal(execution_ack.amount_in),
                    is_paper=execution_ack.is_paper,
                )
                await position.asave()
                logging.warning(f"REPORTER Create new Position #{position.id}")
            else:
                logging.warning(f"REPORTER Update existing Position #{position.id}")

                if not execution_ack.is_buy and position.is_liquidated != 1:
                    position.is_liquidated=1
                    position.liquidated_at=make_aware(datetime.fromtimestamp(int(time())))
                    position.sell_price=Decimal(execution_ack.amount_out)/Decimal(execution_ack.amount_in) if execution_ack.amount_in>0 and not execution_ack.is_buy else 0
                    position.liquidation_attempts=position.liquidation_attempts+1

                    position.pnl=(Decimal(execution_ack.amount_out)-Decimal(position.investment)-Decimal(GAS_COST))/Decimal(position.investment)*Decimal(100) if execution_ack.amount_in>0 and not execution_ack.is_buy else 0
                    position.returns=Decimal(execution_ack.amount_out)

                    await position.asave()

            position_tx = await PositionTransaction.objects.filter(position__id=position.id, transaction__id=tx.id).afirst()
            if position_tx is None:
                position_tx = PositionTransaction(
                    position=position,
                    transaction=tx,
                    is_buy=execution_ack.is_buy,
                )
                await position_tx.asave()
                logging.debug(f"position tx saved id #{position_tx.id}")
            else:
                logging.debug(f"position tx exists id #{position_tx.id}")

            # update PnL
            await update_pnl(position)

        async def save_blacklist(data):
            for addr in data:
                blacklist = await BlackList.objects.filter(address=addr.lower()).afirst()
                if blacklist is None:
                    blacklist = BlackList(
                        address=addr.lower(),
                        frozen_at=make_aware(datetime.now()),
                        )
                    await blacklist.asave()
                    logging.warning(f"REPORTER create blacklist id #{blacklist.id} with address {addr} at {datetime.now()}")
                else:
                    logging.warning(f"REPORTER blacklist {addr} exists, update frozen time {datetime.now()}")
                    blacklist.frozen_at=make_aware(datetime.now())
                    await blacklist.asave()

        try:
            if report.type == ReportDataType.BLOCK:
                await save_block(report)
            elif report.type == ReportDataType.EXECUTION:
                if report.data is not None and isinstance(report.data, ExecutionAck):
                    await save_position(report.data)
            elif report.type == ReportDataType.BLACKLIST_ADDED:
                await save_blacklist(report.data)
            else:
                raise Exception(f"report type {report.type} is unsupported")
            
        except Exception as e:
            logging.error(f"REPORTER save data to db failed with error:: {e}")

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    import aioprocessing

    receiver = aioprocessing.AioQueue()
    sender = aioprocessing.AioQueue()

    reporter = Reporter(receiver, sender)

    # block
    # broker.put(ReportData(
    #     type = ReportDataType.BLOCK,
    #     data = BlockData(
    #         block_number=1,
    #         block_timestamp=1722669970,
    #         base_fee=1000,
    #         gas_used=10000,
    #         gas_limit=10**6,
    #         pairs=[Pair(
    #             address='0xfoo1',
    #             token='0xbar',
    #             token_index=1,
    #             reserve_token=1,
    #             reserve_eth=1,
    #         )],
    #     )
    # ))

    # execution
    receiver.put(ReportData(
        type = ReportDataType.EXECUTION,
        data = ExecutionAck(
            lead_block=1,
            block_number=2,
            tx_hash='0xabc',
            tx_status=0,
            pair=Pair(
                address='0x7c2aa8abd229d4fc658ea98373899ad5746675c3',
                token='0x6d630d5854eede216b5ee453cd4c7682cba6fb22',
                token_index=0,
                reserve_eth=1,
                reserve_token=1,
            ),
            amount_in=1,
            amount_out=0,
            is_buy=False,
            signer='0xecb137C67c93eA50b8C259F8A8D08c0df18222d9',
            bot='0xAfaD9BA8CFaa08fB68820795E8bb33f80d0463a5',
        )
    ))

    # receiver.put(ReportData(
    #     type=ReportDataType.BLACKLIST_ADDED,
    #     data=["0xfoo"]
    # ))

    asyncio.run(reporter.run())
