import asyncio
import aioprocessing
import os
import logging
from decimal import Decimal
from datetime import datetime
import time

from web3 import Web3
from web3.middleware import geth_poa_middleware, construct_sign_and_send_raw_middleware

import sys # for testing
sys.path.append('..')

from library import Singleton
from data import W3Account, BotCreationOrder, Bot, BotUpdateOrder, ExecutionAck
from helpers import timer_decorator, load_abi, constants

import django
from django.utils.timezone import make_aware
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")
django.setup()

import console.models

GAS_LIMIT=int(os.environ.get('CREATE_BOT_GAS_LIMIT'))
BOT_MAX_NUMBER_USED=int(os.environ.get('BOT_MAX_NUMBER_USED'))
RETRY_SLEEP_SECONDS=10

class BotFactory(metaclass=Singleton):
    @timer_decorator
    def __init__(self, http_url, order_broker, result_broker, manager_key, bot_factory, bot_factory_abi, bot_implementation, router, 
                 pair_factory, weth) -> None:
        self.order_broker = order_broker
        self.result_broker = result_broker
        self.retry_queue = aioprocessing.AioQueue()

        self.w3 = Web3(Web3.HTTPProvider(http_url))
        if self.w3.is_connected() == True:
            logging.info(f"FACTORY web3 provider {http_url} connected")

        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        self.manager = self.w3.eth.account.from_key(manager_key)
        self.w3.middleware_onion.add(construct_sign_and_send_raw_middleware(self.manager))
        self.w3.eth.default_account = self.manager.address

        self.bot_factory = self.w3.eth.contract(address=bot_factory,abi=bot_factory_abi)
        self.bot_implementation = Web3.to_checksum_address(bot_implementation)

        self.router = Web3.to_checksum_address(router)
        self.pair_factory = Web3.to_checksum_address(pair_factory)
        self.weth = Web3.to_checksum_address(weth)

    @timer_decorator
    def create_bot(self, owner) -> None:
        try:
            nonce = self.w3.eth.get_transaction_count(self.manager.address)
            tx = self.bot_factory.functions.createBot(self.bot_implementation,
                                                    Web3.keccak(text=str(time.time())),
                                                    Web3.to_checksum_address(owner),
                                                    self.router,
                                                    self.pair_factory,
                                                    self.weth,
                                                    ).build_transaction({
                                                        "from": self.manager.address,
                                                        "nonce": nonce,
                                                        "gas": GAS_LIMIT,
                                                    })
            tx_hash = self.w3.eth.send_transaction(tx)
            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if tx_receipt['status'] == constants.TX_SUCCESS_STATUS:
                bot_created_logs = self.bot_factory.events.BotCreated().process_receipt(tx_receipt)
                logging.info(f"FACTORY successfully create bot with owner {owner} at {bot_created_logs[0]['args']['bot']}")

                return Bot(
                    address=bot_created_logs[0]['args']['bot'],
                    owner=bot_created_logs[0]['args']['owner'],
                    deployed_at=int(time.time()),
                    number_used=0,
                    is_failed=False
                )
            else:
                logging.error(f"FACTORY create bot with owner {owner} failed {tx_receipt}")

        except Exception as e:
            logging.error(f"FACTORY create bot with owner {owner} error:: {e}")

    async def handle_create_bot(self, order: BotCreationOrder):
        try:
            # query from DB
            bot = await console.models.Bot.objects.filter(owner=order.owner.lower()).filter(number_used__lt=BOT_MAX_NUMBER_USED).filter(is_failed=False).afirst()
            if bot is not None:
                logging.info(f"FACTORY found available bot #{bot.id} from DB")

                # send result via broker
                self.result_broker.put(Bot(
                    address=bot.address,
                    owner=bot.owner,
                    deployed_at=int(datetime.timestamp(bot.deployed_at)),
                    number_used=bot.number_used,
                    is_failed=bot.is_failed,
                ))
            else:
                bot = self.create_bot(order.owner)
                if bot is not None and isinstance(bot, Bot):
                    # save to DB
                    obj = console.models.Bot(
                        address=bot.address.lower(),
                        owner=bot.owner.lower(),
                        deployed_at=make_aware(datetime.now()),
                        number_used=0,
                        is_failed=False,
                    )
                    await obj.asave()
                    logging.info(f"FACTORY save bot to DB #{obj.id}")

                    # send result via broker
                    self.result_broker.put(bot)
                else:
                    logging.error(f"FACTORY create bot for owner {order.owner} failed, retry...")
                    await asyncio.sleep(RETRY_SLEEP_SECONDS)
                    self.order_broker.put(BotCreationOrder(owner=order.owner, retry_times=order.retry_times+1))
        except Exception as e:
            logging.error(f"FACTORY handle create-bot error {e}")

    async def handle_update_bot(self, order: BotUpdateOrder):
        try:
            bot = await console.models.Bot.objects.filter(address=order.bot.address.lower()).afirst()
            if bot is not None:
                if order.execution_ack.is_buy:
                    bot.is_holding=True
                    await bot.asave()
                else:
                    bot.is_holding=False
                    bot.number_used=bot.number_used+1
                    if order.execution_ack.tx_status != constants.TX_SUCCESS_STATUS:
                        bot.is_failed=True
                    await bot.asave()
                logging.info(f"FACTORY updated status for bot {bot}")
            else:
                logging.warning(f"FACTORY not found bot {bot} to update")
        except Exception as e:
            logging.error(f"FACTORY handle update-bot error {e}")

    async def run(self):
        while True:
            order = await self.order_broker.coro_get()

            if order is not None and isinstance(order, BotCreationOrder):
                logging.info(f"FACTORY receive bot-create order {order}")
                await self.handle_create_bot(order)
            elif order is not None and isinstance(order, BotUpdateOrder):
                logging.info(f"FACTORY receive bot-update order {order.bot}")
                await self.handle_update_bot(order)
            else:
                logging.error(f"FACTORY invalid order {order}")

if __name__=="__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    BOT_FACTORY_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/BotFactory.abi.json")

    order_broker = aioprocessing.AioQueue()
    result_broker = aioprocessing.AioQueue()

    factory = BotFactory(
        http_url=os.environ.get('HTTPS_URL'),
        order_broker=order_broker,
        result_broker=result_broker,
        manager_key=os.environ.get('MANAGER_KEY'),
        bot_factory=os.environ.get('BOT_FACTORY'),
        bot_factory_abi=BOT_FACTORY_ABI,
        bot_implementation=os.environ.get('BOT_IMPLEMENTATION'),
        router=os.environ.get('ROUTER_ADDRESS'),
        pair_factory=os.environ.get('FACTORY_ADDRESS'),
        weth=os.environ.get('WETH_ADDRESS'),
    )

    order_broker.put(BotCreationOrder(owner='0xecb137C67c93eA50b8C259F8A8D08c0df18222d9'))

    async def handle_result():
        while True:
            result = await result_broker.coro_get()
            if result is not None:
                logging.info(f"Bot creation result {result}")

    async def main_loop():
        await asyncio.gather(factory.run(),handle_result())

    asyncio.run(main_loop())