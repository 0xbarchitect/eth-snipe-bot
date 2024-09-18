import asyncio
import aioprocessing
import os
import logging
import time
from decimal import Decimal
import threading

from concurrent.futures import ThreadPoolExecutor
from web3 import Web3
from web3.logs import STRICT, IGNORE, DISCARD, WARN

import sys # for testing
sys.path.append('..')

from helpers import timer_decorator, load_abi, constants
from executor import BaseExecutor
from data import ExecutionOrder, Pair, ExecutionAck, TxStatus, BotCreationOrder, Bot, BotUpdateOrder, Position
from factory import BotFactory
from inspector import EthCallSimulator

glb_lock = threading.Lock()
BOT_MAX_NUMBER_USED=int(os.environ.get('BOT_MAX_NUMBER_USED'))
EXECUTION_GAS_LIMIT=int(os.environ.get('EXECUTION_GAS_LIMIT'))

class BuySellExecutor(BaseExecutor):
    def __init__(self, http_url, treasury_key, executor_keys, order_receiver, report_sender, \
                gas_limit, max_fee_per_gas, max_priority_fee_per_gas, deadline_delay, \
                weth, router, router_abi, erc20_abi, pair_abi, bot, bot_abi, \
                manager_key, bot_factory, bot_factory_abi, bot_implementation, pair_factory, bot_db=True) -> None:
        super().__init__(http_url, treasury_key, executor_keys, order_receiver, report_sender, gas_limit, max_fee_per_gas, max_priority_fee_per_gas, deadline_delay)
        
        self.weth = weth
        self.router = self.w3.eth.contract(address=router, abi=router_abi)
        self.erc20_abi = erc20_abi
        self.pair_abi = pair_abi

        # bot factory initialize
        self.bot_db = bot_db
        self.bot_abi = bot_abi
        self.bot_order_broker = aioprocessing.AioQueue()
        self.bot_result_broker = aioprocessing.AioQueue()

        if self.bot_db:
            self.bot_factory = BotFactory(
                http_url=http_url,
                order_broker=self.bot_order_broker,
                result_broker=self.bot_result_broker,
                manager_key=manager_key,
                bot_factory=bot_factory,
                bot_factory_abi=bot_factory_abi,
                bot_implementation=bot_implementation,
                router=router,
                pair_factory=pair_factory,
                weth=weth,
            )
    
            for acct in self.accounts:
                self.bot_order_broker.put(BotCreationOrder(owner=acct.w3_account.address))

        # paper-trade
        self.simulator = EthCallSimulator(
            http_url=http_url,
            signer=Web3.to_checksum_address(os.environ.get('MANAGER_ADDRESS')),
            bot=Web3.to_checksum_address(os.environ.get('INSPECTOR_BOT')),
        )
            
    @timer_decorator
    def execute(self, idx, lead_block, is_buy, pair, amount_in, amount_out_min, deadline, bot=None):
        def prepare_tx_bot(signer, bot, nonce):
            tx = None            
            if is_buy:
                tx = bot.functions.buy(Web3.to_checksum_address(pair.token), deadline).build_transaction({
                    "from": signer,
                    "nonce": nonce,
                    "gas": self.gas_limit,
                    "value": Web3.to_wei(amount_in, 'ether'),
                })
            else:
                tx = bot.functions.sell(Web3.to_checksum_address(pair.token), signer, deadline).build_transaction({
                    "from": signer,
                    "nonce": nonce,
                    "gas": self.gas_limit,
                })

            return tx
        
        signer = self.accounts[idx].w3_account.address
        priv_key = self.accounts[idx].private_key
        if bot is None:
            bot = self.w3.eth.contract(address=Web3.to_checksum_address(self.accounts[idx].bot.address),abi=self.bot_abi)
        else:
            bot = self.w3.eth.contract(address=Web3.to_checksum_address(bot),abi=self.bot_abi)

        try:
            logging.warning(f"EXECUTOR Signer {signer} AmountIn {amount_in} AmountOutMin {amount_out_min} Deadline {deadline} IsBuy {is_buy}")

            # get nonce onchain
            nonce = self.w3.eth.get_transaction_count(signer)

            tx = prepare_tx_bot(signer, bot, nonce)
            
            if tx is None:
                raise Exception(f"create tx failed")
            
            # send raw tx
            signed = self.w3.eth.account.sign_transaction(tx, priv_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            logging.debug(f"created tx hash {Web3.to_hex(tx_hash)}")

            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            logging.debug(f"tx receipt {tx_receipt}")
            logging.debug(f"{amount_in} tx hash {Web3.to_hex(tx_hash)} in block #{tx_receipt['blockNumber']} with status {tx_receipt['status']}")

            # send acknowledgement
            amount_out = 0
            if tx_receipt['status'] == TxStatus.SUCCESS:
                pair_contract = self.w3.eth.contract(address=Web3.to_checksum_address(pair.address), abi=self.pair_abi)
                swap_logs = pair_contract.events.Swap().process_receipt(tx_receipt, errors=DISCARD)
                logging.debug(f"swap logs {swap_logs[0]}")

                swap_logs = swap_logs[0]

                amount_out = Web3.from_wei(swap_logs['args']['amount0Out'], 'ether') if pair.token_index==0 else Web3.from_wei(swap_logs['args']['amount1Out'], 'ether')
                if not is_buy:
                    amount_out = Web3.from_wei(swap_logs['args']['amount1Out'], 'ether') if pair.token_index==0 else Web3.from_wei(swap_logs['args']['amount0Out'], 'ether')

            ack = ExecutionAck(
                lead_block=lead_block,
                block_number=tx_receipt['blockNumber'],
                tx_hash=Web3.to_hex(tx_hash),
                tx_status=tx_receipt['status'],
                pair=pair,
                amount_in=amount_in,
                amount_out=amount_out,
                is_buy=is_buy,
                signer=signer,
                bot=bot.address,
            )

            logging.warning(f"EXECUTOR Acknowledgement {ack}")
            self.report_sender.put(ack)

        except Exception as e:
            logging.warning(f"EXECUTOR order {pair} amountIn {amount_in} isBuy {is_buy} catch exception {e}")
            ack = ExecutionAck(
                lead_block=lead_block,
                block_number=lead_block,
                tx_hash='0x',
                tx_status=TxStatus.FAILED,
                pair=pair,
                amount_in=amount_in,
                amount_out=0,
                is_buy=is_buy,
                signer=signer,
                bot=bot.address,
            )

            logging.warning(f"EXECUTOR failed execution ack {ack}")
            self.report_sender.put(ack)

        # update bot status
        if self.bot_db and self.accounts[idx].bot is not None:
            self.bot_factory.order_broker.put(BotUpdateOrder(self.accounts[idx].bot,ack))
            if ack.is_buy:
                self.accounts[idx].bot.is_holding=True
            else:
                self.accounts[idx].bot.is_holding=False
                self.accounts[idx].bot.number_used=self.accounts[idx].bot.number_used+1
                if ack.tx_status != constants.TX_SUCCESS_STATUS:
                    self.accounts[idx].bot.is_failed=True

                # renew bot
                if self.accounts[idx].bot.number_used>=BOT_MAX_NUMBER_USED or self.accounts[idx].bot.is_failed:
                    logging.warning(f"EXECUTOR bot {self.accounts[idx].bot.address} of account {signer} reached max usage {BOT_MAX_NUMBER_USED} or failure, replace it with new created bot")
                    self.accounts[idx].bot = None
                    self.bot_factory.order_broker.put(BotCreationOrder(self.accounts[idx].w3_account.address))

    @timer_decorator
    def execute_paper(self, idx, lead_block, is_buy, pair, amount_in, amount_out_min, deadline, bot=None):
        signer = self.accounts[idx].w3_account.address
        if bot is None:
            bot = self.w3.eth.contract(address=Web3.to_checksum_address(self.accounts[idx].bot.address),abi=self.bot_abi)
        else:
            bot = self.w3.eth.contract(address=Web3.to_checksum_address(bot),abi=self.bot_abi)

        if is_buy:
            result = self.simulator.buy(pair.token, amount_in, signer, bot.address)
            logging.warning(f"EXECUTOR Paper:: Buy result {result}")
        else:
            result = self.simulator.sell(pair.token, amount_in, signer, bot.address)
            logging.warning(f"EXECUTOR Paper:: Sell result {result}")

        if result is not None:
            ack = ExecutionAck(
                lead_block=lead_block,
                block_number=lead_block,
                tx_hash='0x',
                tx_status=TxStatus.SUCCESS,
                pair=pair,
                amount_in=amount_in,
                amount_out=Web3.from_wei(result[0][1], 'ether'),
                is_buy=is_buy,
                signer=signer,
                bot=bot.address,
                is_paper=True,
            )

            logging.info(f"EXECUTOR Acknowledgement {ack}")
            self.report_sender.put(ack)
        else:
            ack = ExecutionAck(
                lead_block=lead_block,
                block_number=lead_block,
                tx_hash='0x',
                tx_status=TxStatus.FAILED,
                pair=pair,
                amount_in=amount_in,
                amount_out=0,
                is_buy=is_buy,
                signer=signer,
                bot=bot.address,
                is_paper=True,
            )

            logging.info(f"EXECUTOR failed execution ack {ack}")
            self.report_sender.put(ack)

    async def handle_bot_result(self):
        while True:
            result = await self.bot_result_broker.coro_get()

            if result is not None and isinstance(result, Bot):
                logging.debug(f"EXECUTOR bot created {result}")
                for idx,acct in enumerate(self.accounts):
                    if (acct.bot is None or acct.bot.number_used >= BOT_MAX_NUMBER_USED or acct.bot.is_failed) and acct.w3_account.address.lower()==result.owner.lower():
                        logging.warning(f"EXECUTOR created bot {result} for account #{idx} {acct.w3_account.address}")
                        acct.bot = result

    async def handle_execution_order(self):
        global glb_lock

        logging.warning(f"EXECUTOR listen for order...")
        executor = ThreadPoolExecutor(max_workers=len(self.accounts))
        counter = 0
        while True:
            execution_data = await self.order_receiver.coro_get()

            if execution_data is not None and isinstance(execution_data, ExecutionOrder):
                with glb_lock:
                    counter += 1

                logging.warning(f"EXECUTOR receive order #{counter} {execution_data}")
                deadline = execution_data.block_timestamp + self.deadline_delay if execution_data.block_timestamp > 0 else self.get_block_timestamp() + self.deadline_delay
                
                if execution_data.signer is None:
                    idx = (counter - 1) % len(self.accounts)

                    if self.accounts[idx].bot is not None:
                        if execution_data.is_paper:
                            future = executor.submit(self.execute_paper,
                                                idx,
                                                execution_data.block_number,
                                                execution_data.is_buy,
                                                execution_data.pair,
                                                execution_data.amount_in,
                                                execution_data.amount_out_min, 
                                                deadline,
                                                )
                        else:
                            future = executor.submit(self.execute,
                                                idx,
                                                execution_data.block_number,
                                                execution_data.is_buy,
                                                execution_data.pair,
                                                execution_data.amount_in,
                                                execution_data.amount_out_min, 
                                                deadline,
                                                )
                    else:
                        logging.warning(f"EXECUTOR order dropped due to account #{idx} {self.accounts[idx].w3_account.address} has no bot")
                else:
                    idx = None
                    for idx, acct in enumerate(self.accounts):
                        if acct.w3_account.address.lower() == execution_data.signer.lower():
                            id = idx
                            break
                    if idx is not None:
                        if execution_data.is_paper:
                            future = executor.submit(self.execute_paper,
                                idx,
                                execution_data.block_number,
                                execution_data.is_buy,
                                execution_data.pair,
                                execution_data.amount_in,
                                execution_data.amount_out_min, 
                                deadline,
                                execution_data.bot,
                            )
                        else:
                            future = executor.submit(self.execute,
                                idx,
                                execution_data.block_number,
                                execution_data.is_buy,
                                execution_data.pair,
                                execution_data.amount_in,
                                execution_data.amount_out_min, 
                                deadline,
                                execution_data.bot,
                            )
                    else:
                        logging.error(f"EXECUTOR not found signer for order {execution_data}")
            else:
                logging.warning(f"EXECUTOR invalid order {execution_data}")

    async def run(self):
        if self.bot_db:
            await asyncio.gather(self.handle_execution_order(), self.bot_factory.run(), self.handle_bot_result())
        else:
            await self.handle_execution_order()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    ROUTER_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/UniRouter.abi.json")
    WETH_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/WETH.abi.json")
    ERC20_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/ERC20.abi.json")
    PAIR_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/UniV2Pair.abi.json")
    BOT_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/SnipeBot.abi.json")
    BOT_FACTORY_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/BotFactory.abi.json")

    order_receiver = aioprocessing.AioQueue()
    report_sender = aioprocessing.AioQueue()

    executor = BuySellExecutor(
        http_url=os.environ.get('HTTPS_URL'),
        treasury_key=os.environ.get('MANAGER_KEY'),
        executor_keys=os.environ.get('EXECUTION_KEYS').split(','),
        order_receiver=order_receiver,
        report_sender=report_sender,
        gas_limit=EXECUTION_GAS_LIMIT,
        max_fee_per_gas=0.01*10**9,
        max_priority_fee_per_gas=25*10**9,
        deadline_delay=30,
        weth=os.environ.get('WETH_ADDRESS'),
        router=os.environ.get('ROUTER_ADDRESS'),
        router_abi=ROUTER_ABI,
        erc20_abi=ERC20_ABI,
        pair_abi=PAIR_ABI,
        bot=os.environ.get('INSPECTOR_BOT').split(','),
        bot_abi=BOT_ABI,
        manager_key=os.environ.get('MANAGER_KEY'),
        bot_factory=os.environ.get('BOT_FACTORY'),
        bot_factory_abi=BOT_FACTORY_ABI,
        bot_implementation=os.environ.get('BOT_IMPLEMENTATION'),
        pair_factory=os.environ.get('FACTORY_ADDRESS'),
        bot_db=False,
    )

    async def simulate_order():
        await asyncio.sleep(1) # waiting for bot is fully initialized

        pair=Pair(
            address='0xac318fc97c8b9133a6541eaa57f37d9d51b2451c',
            token='0xf16b58d2bdb36a9be9ba9d4b847b909bf7297955',
            token_index=1,
        )
        # BUY
        # order_receiver.put(ExecutionOrder(
        #     block_number=0, 
        #     block_timestamp=0, 
        #     pair=pair,
        #     signer='0xecb137C67c93eA50b8C259F8A8D08c0df18222d9',
        #     bot='0xadfd91a139c36715d09bf97943e6ac8d48f00f4b',
        #     amount_in=0.001667,
        #     amount_out_min=0,
        #     is_buy=True,
        #     is_paper=True,
        # ))
        
        # SELL
        order_receiver.put(ExecutionOrder(
            block_number=0,
            block_timestamp=0,
            pair=pair,
            signer='0x0815e09b64994fac24f919c90af4fdd1bbec06d9',
            bot='0x090effb0722ea3a2acd5cc96e2531658fee79db9',
            amount_in=6842714.885,
            amount_out_min=0,
            is_buy=False,
            is_paper=False,
        ))

    async def main_loop():
        await asyncio.gather(executor.run(), simulate_order())
    
    asyncio.run(main_loop())