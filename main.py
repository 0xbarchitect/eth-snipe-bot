import asyncio
import aioprocessing
from multiprocessing import Process
import threading
import concurrent.futures

from web3 import Web3
import os
import sys
import signal
import logging
from decimal import Decimal
from time import time
from datetime import datetime, timedelta
from typing import List

from dotenv import load_dotenv
load_dotenv()
#logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=int(os.environ.get('LOG_LEVEL')))

from watcher import BlockWatcher
from inspector import PairInspector
from executor import BuySellExecutor
from reporter import Reporter
from helpers import load_abi, timer_decorator, calculate_price, calculate_next_block_base_fee, \
                        constants, get_hour_in_vntz, calculate_expect_pnl, determine_epoch, GasHelper

from data import ExecutionOrder, SimulationResult, ExecutionAck, Position, TxStatus, \
                    ReportData, ReportDataType, BlockData, Pair, MaliciousPair, InspectionResult, \
                    ControlOrder, ControlOrderType

# global variables
glb_fullfilled = 0
glb_liquidated = False
glb_watchlist = []
glb_inventory = []
glb_daily_pnl = (datetime.now(), 0)
glb_auto_run = True
glb_lock = threading.Lock()

# load config
ERC20_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/ERC20.abi.json")
PAIR_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/UniV2Pair.abi.json")
WETH_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/WETH.abi.json")
ROUTER_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/UniRouter.abi.json")
FACTORY_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/UniV2Factory.abi.json")
BOT_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/SnipeBot.abi.json")
BOT_FACTORY_ABI = load_abi(f"{os.path.dirname(__file__)}/contracts/abis/BotFactory.abi.json")

# simulation conditions
RUN_MODE=int(os.environ.get('RUN_MODE', '0'))

RESERVE_ETH_MIN_THRESHOLD=float(os.environ.get('RESERVE_ETH_MIN_THRESHOLD'))
RESERVE_ETH_MAX_THRESHOLD=float(os.environ.get('RESERVE_ETH_MAX_THRESHOLD'))

# watchlist config
MAX_INSPECT_ATTEMPTS=int(os.environ.get('MAX_INSPECT_ATTEMPTS'))
INSPECT_INTERVAL_SECONDS=int(os.environ.get('INSPECT_INTERVAL_SECONDS'))
WATCHLIST_CAPACITY = 100
NUMBER_TX_MM_THRESHOLD=int(os.environ.get('NUMBER_TX_MM_THRESHOLD'))

# buy/sell tx config
INVENTORY_CAPACITY=int(os.environ.get('INVENTORY_CAPACITY'))
BUY_AMOUNT=float(os.environ.get('BUY_AMOUNT'))
AMOUNT_CHANGE_STEP=float(os.environ.get('AMOUNT_CHANGE_STEP'))
MIN_BUY_AMOUNT=float(os.environ.get('MIN_BUY_AMOUNT'))
MAX_BUY_AMOUNT=float(os.environ.get('MAX_BUY_AMOUNT'))
MIN_EXPECTED_PNL=float(os.environ.get('MIN_EXPECTED_PNL'))
RISK_REWARD_RATIO=float(os.environ.get('RISK_REWARD_RATIO'))
EPOCH_TIME_HOURS=int(os.environ.get('EPOCH_TIME_HOURS'))
MAX_GAS_PRICE_ALLOWANCE=float(os.environ.get('MAX_GAS_PRICE_ALLOWANCE'))

DEADLINE_DELAY_SECONDS = 30
GAS_LIMIT = 250*10**3
MAX_FEE_PER_GAS = 10**9
MAX_PRIORITY_FEE_PER_GAS = 10**9
GAS_COST=float(os.environ.get('GAS_COST_GWEI'))*10**-9

# liquidation conditions
TAKE_PROFIT_PERCENTAGE=float(os.environ.get('TAKE_PROFIT_PERCENTAGE'))
STOP_LOSS_PERCENTAGE=float(os.environ.get('STOP_LOSS_PERCENTAGE'))
HOLD_MAX_DURATION_SECONDS=int(os.environ.get('HOLD_MAX_DURATION_SECONDS'))
HARD_STOP_PNL_THRESHOLD=int(os.environ.get('HARD_STOP_PNL_THRESHOLD'))

async def watching_process(watching_broker, watching_notifier):
    block_watcher = BlockWatcher(os.environ.get('HTTPS_URL'),
                                os.environ.get('WSS_URL'), 
                                watching_broker, 
                                watching_notifier,
                                os.environ.get('FACTORY_ADDRESS'),
                                FACTORY_ABI,
                                os.environ.get('WETH_ADDRESS'),
                                PAIR_ABI,
                                )
    await block_watcher.main()

async def strategy(watching_broker, execution_broker, report_broker, watching_notifier,):
    global glb_fullfilled
    global glb_liquidated
    global glb_lock
    global glb_inventory
    global glb_watchlist
    global glb_daily_pnl
    global glb_auto_run
    global BUY_AMOUNT

    gas_helper = GasHelper(os.environ.get('ETHERSCAN_API_URL'), os.environ.get('BASESCAN_API_KEYS'))
    #print(f"!!!! GAS_PRICE {gas_helper.get_base_gas_price()}")

    def calculate_pnl_percentage(position, pair):        
        numerator = Decimal(position.amount)*calculate_price(pair.reserve_token, pair.reserve_eth) - Decimal(BUY_AMOUNT) - Decimal(GAS_COST)
        denominator = Decimal(BUY_AMOUNT)
        return (numerator / denominator) * Decimal(100)
    
    def send_exec_order(block_data, pair, is_paper=False):
        global glb_fullfilled

        gas_price = gas_helper.get_base_gas_price()
        if gas_price>MAX_GAS_PRICE_ALLOWANCE:
            logging.error(f"Cancel execution due to Gas price {gas_price} is greater than max allowance {MAX_GAS_PRICE_ALLOWANCE}")
            return None

        if glb_fullfilled < INVENTORY_CAPACITY:
            with glb_lock:
                glb_fullfilled += 1

            # send execution order
            logging.warning(f"MAIN send buy-order of {pair.address} amount {BUY_AMOUNT}")
            execution_broker.put(ExecutionOrder(
                block_number=block_data.block_number,
                block_timestamp=block_data.block_timestamp,
                pair=pair,
                amount_in=BUY_AMOUNT,
                amount_out_min=0,
                is_buy=True,
                is_paper=is_paper,
            ))
        else:
            logging.warning(f"MAIN inventory capacity {INVENTORY_CAPACITY} is full")

    while True:
        block_data = await watching_broker.coro_get()
        logging.info(f"MAIN received block {block_data}")
        
        # send block report
        if len(block_data.pairs) > 0:
            report_broker.put(ReportData(
                type=ReportDataType.BLOCK,
                data=block_data,
            ))

        # hardstop based on pnl
        logging.info(f"[{glb_daily_pnl[0].strftime('%Y-%m-%d %H:00:00')}] Realized PnL {round(glb_daily_pnl[1],6)} Epoch {determine_epoch(EPOCH_TIME_HOURS)} Expected PnL {round(calculate_expect_pnl(BUY_AMOUNT, MIN_BUY_AMOUNT, MIN_EXPECTED_PNL, RISK_REWARD_RATIO),6)}")

        if RUN_MODE==constants.WATCHING_ONLY_MODE:
            logging.info(f"I'm happy watching =))...")
            continue

        if len(glb_inventory)>0:
            if not glb_liquidated:
                for idx,position in enumerate(glb_inventory):
                    is_liquidated = False
                    for pair in block_data.inventory:
                        if position.pair.address == pair.address:
                            position.pnl = calculate_pnl_percentage(position, pair)
                            logging.warning(f"MAIN {position} update PnL {position.pnl}")
                            
                            if position.pnl > Decimal(TAKE_PROFIT_PERCENTAGE) or position.pnl < Decimal(STOP_LOSS_PERCENTAGE):
                                logging.warning(f"MAIN {position} take profit or stop loss caused by pnl {position.pnl}")
                                is_liquidated = True
                                break

                    if not is_liquidated and block_data.block_timestamp - position.start_time > HOLD_MAX_DURATION_SECONDS:
                        logging.warning(f"MAIN {position} liquidation call caused by timeout {HOLD_MAX_DURATION_SECONDS}")
                        is_liquidated = True

                    if is_liquidated:
                        with glb_lock:
                            glb_liquidated = True
                            glb_inventory.pop(idx)
                        logging.warning(f"MAIN Remove {position} from inventory at index #{idx}")

                        execution_broker.put(ExecutionOrder(
                                    block_number=block_data.block_number,
                                    block_timestamp=block_data.block_timestamp,
                                    pair=position.pair,
                                    amount_in=position.amount,
                                    amount_out_min=0,
                                    is_buy=False,
                                    signer=position.signer,
                                    bot=position.bot,
                                    is_paper=position.is_paper,
                                ))
        
        if glb_daily_pnl[1] < HARD_STOP_PNL_THRESHOLD and glb_auto_run:
            with glb_lock:
                glb_auto_run = False
                logging.warning(f"MAIN stop auto run...")

        if not glb_auto_run:
            logging.info(f"MAIN auto-run is disabled")
            continue

        if glb_daily_pnl[0].strftime('%Y-%m-%d %H') != datetime.now().strftime('%Y-%m-%d %H'):
            if get_hour_in_vntz(datetime.now()) % EPOCH_TIME_HOURS == 0:
                with glb_lock:
                    glb_daily_pnl = (datetime.now(), 0)
                    logging.warning(f"MAIN reset epoch pnl at {glb_daily_pnl[0].strftime('%Y-%m-%d %H:00:00')}")

            if get_hour_in_vntz(datetime.now())==0:
                with glb_lock:
                    BUY_AMOUNT=float(os.environ.get('BUY_AMOUNT'))
                    logging.warning(f"MAIN reset buy-amount to initial value {BUY_AMOUNT} at 0am VNT")

        if len(glb_watchlist)>0:
            logging.info(f"MAIN watching list {len(glb_watchlist)}")

            inspection_batch=[]
            for pair in glb_watchlist:
                if (block_data.block_timestamp - pair.created_at) > pair.inspect_attempts*INSPECT_INTERVAL_SECONDS:
                    logging.warning(f"MAIN pair {pair.address} inspect time #{pair.inspect_attempts + 1} elapsed")
                    inspection_batch.append(pair)

            if len(inspection_batch)>0:
                results = inspect(inspection_batch, block_data.block_number)
                logging.debug(f"MAIN watchlist simulation result length {len(results)}")

                for result in results:
                    if result.simulation_result is not None:
                        for idx,pair in enumerate(glb_watchlist):
                            if result.pair.address == pair.address:
                                with glb_lock:
                                    pair.inspect_attempts += 1
                                    pair.number_tx_mm = result.number_tx_mm
                                    pair.contract_verified = result.contract_verified if not pair.contract_verified else pair.contract_verified
                                    # TODO: last_inspected_block is not updated and stay as initial value created_block_number
                                    # in order to re-verify multiple times to gain reliability
                                    #pair.last_inspected_block = block_data.block_number
                                    
                                logging.warning(f"MAIN update upon inspect attempts {pair}")

                            if pair.inspect_attempts >= MAX_INSPECT_ATTEMPTS:
                                with glb_lock:
                                    glb_watchlist.pop(idx)
                                logging.warning(f"MAIN remove pair {pair.address} from watching list at index #{idx} caused by reaching max attempts {MAX_INSPECT_ATTEMPTS}")

                                if pair.number_tx_mm >= NUMBER_TX_MM_THRESHOLD and pair.contract_verified:
                                    is_paper = True if RUN_MODE==constants.PAPER_TRADE_MODE else False
                                    send_exec_order(block_data,pair,is_paper)
                                else:
                                    logging.warning(f"MAIN pair {pair.address} not qualified for execution due to numberTxMM {pair.number_tx_mm} is not sufficient or contract unverified")

                # remove simulation failed pair
                failed_pairs = [pair.address for pair in inspection_batch if pair.address not in [result.simulation_result.pair.address for result in results if result.simulation_result is not None]]
                for idx,pair in enumerate(glb_watchlist):
                    if pair.address in failed_pairs:
                        with glb_lock:
                            glb_watchlist.pop(idx)

                        logging.warning(f"MAIN remove pair {pair.address} from watchlist at index #{idx} due to inspection failed")

        if  len(block_data.pairs)>0:
            results = inspect(block_data.pairs, block_data.block_number, is_initial=True)
            logging.debug(f"MAIN inspection results length {len(results)}")

            if len(glb_watchlist)<WATCHLIST_CAPACITY:
                for result in results:
                    if result.simulation_result is not None:
                        if MAX_INSPECT_ATTEMPTS > 1:
                            with glb_lock:
                                # append to watchlist
                                pair=result.pair
                                pair.inspect_attempts=1
                                pair.last_inspected_block=block_data.block_number
                                pair.contract_verified=result.contract_verified
                                pair.number_tx_mm=result.number_tx_mm

                                glb_watchlist.append(pair)

                            logging.warning(f"MAIN add pair {pair.address} to watchlist length {len(glb_watchlist)}")
                        else:
                            # send order immediately
                            send_exec_order(block_data, result.pair)
            else:
                logging.warning(f"MAIN watchlist is already full capacity")

@timer_decorator
def inspect(pairs, block_number, is_initial=False) -> List[InspectionResult]:

    inspector = PairInspector(
        http_url=os.environ.get('HTTPS_URL'),
        api_keys=os.environ.get('BASESCAN_API_KEYS'),
        etherscan_api_url=os.environ.get('ETHERSCAN_API_URL'),
        signer=Web3.to_checksum_address(os.environ.get('MANAGER_ADDRESS')),
        router=Web3.to_checksum_address(os.environ.get('ROUTER_ADDRESS')),
        weth=Web3.to_checksum_address(os.environ.get('WETH_ADDRESS')),
        bot=Web3.to_checksum_address(os.environ.get('INSPECTOR_BOT')),
        pair_abi=PAIR_ABI,
        weth_abi=WETH_ABI,
        bot_abi=BOT_ABI,
    )

    return inspector.inspect_batch(pairs,block_number, is_initial)

def execution_process(execution_broker, report_broker):
    # set process group the same as main process
    os.setpgid(0, os.getppid())

    executor = BuySellExecutor(
        http_url=os.environ.get('HTTPS_URL'),
        treasury_key=os.environ.get('MANAGER_KEY'),
        executor_keys=os.environ.get('EXECUTION_KEYS').split(','),
        order_receiver=execution_broker,
        report_sender=report_broker,
        gas_limit=GAS_LIMIT,
        max_fee_per_gas=MAX_FEE_PER_GAS,
        max_priority_fee_per_gas=MAX_PRIORITY_FEE_PER_GAS,
        deadline_delay=DEADLINE_DELAY_SECONDS,
        weth=Web3.to_checksum_address(os.environ.get('WETH_ADDRESS')),
        router=Web3.to_checksum_address(os.environ.get('ROUTER_ADDRESS')),
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
    )

    asyncio.run(executor.run())

async def main():
    global glb_inventory
    global glb_lock
    global glb_fullfilled

    watching_broker = aioprocessing.AioQueue()
    watching_notifier = aioprocessing.AioQueue()
    execution_broker = aioprocessing.AioQueue()
    execution_report = aioprocessing.AioQueue()
    report_broker = aioprocessing.AioQueue()
    control_receiver = aioprocessing.AioQueue()

    # set process group
    os.setpgid(0, 0)
    
    # EXECUTION process
    p2 = Process(target=execution_process, args=(execution_broker,execution_report,))
    p2.start()

    # REPORTING process
    reporter = Reporter(report_broker, control_receiver)

    async def handle_execution_report():
        global glb_inventory
        global glb_lock
        global glb_fullfilled
        global glb_liquidated
        global glb_daily_pnl
        global BUY_AMOUNT

        while True:
            report = await execution_report.coro_get()
            logging.warning(f"MAIN receive execution report {report}")

            if report is not None and isinstance(report, ExecutionAck):
                # send execution report
                report_broker.put(ReportData(
                    type=ReportDataType.EXECUTION,
                    data=report,
                ))

                watching_notifier.put(report)

                if report.tx_status == TxStatus.SUCCESS:
                    if report.is_buy:
                        with glb_lock:
                            glb_inventory.append(Position(
                                pair=report.pair,
                                amount=report.amount_out,
                                buy_price=calculate_price(report.amount_out, report.amount_in),
                                start_time=int(time()),
                                signer=report.signer,
                                bot=report.bot,
                                is_paper=report.is_paper,
                            ))
                            logging.warning(f"MAIN append {report.pair.address} to inventory length {len(glb_inventory)}")
                    else:
                        with glb_lock:
                            glb_fullfilled -= 1
                            glb_liquidated = False

                            pnl = (Decimal(report.amount_out)-Decimal(BUY_AMOUNT)-Decimal(GAS_COST))/Decimal(BUY_AMOUNT)*Decimal(100)
                            glb_daily_pnl = (glb_daily_pnl[0], glb_daily_pnl[1] + pnl)

                            # if PnL exceed threshold then increase the buy-amount and reset the PnL
                            if glb_daily_pnl[1]>calculate_expect_pnl(BUY_AMOUNT,MIN_BUY_AMOUNT,MIN_EXPECTED_PNL,RISK_REWARD_RATIO) and BUY_AMOUNT+AMOUNT_CHANGE_STEP<=MAX_BUY_AMOUNT:
                                BUY_AMOUNT+=AMOUNT_CHANGE_STEP
                                glb_daily_pnl = (glb_daily_pnl[0], 0)
                                logging.warning(f"MAIN increase buy-amount to {BUY_AMOUNT} caused by PnL exceed threshold {calculate_expect_pnl(BUY_AMOUNT,MIN_BUY_AMOUNT,MIN_EXPECTED_PNL,RISK_REWARD_RATIO)}, reset PnL")

                            logging.warning(f"MAIN update PnL {glb_daily_pnl}")
                else:
                    logging.warning(f"MAIN execution failed, reset lock...")
                    if report.is_buy:
                        with glb_lock:
                            glb_fullfilled -= 1
                    else:
                        with glb_lock:
                            glb_fullfilled -= 1
                            glb_liquidated = False

                            pnl = (-Decimal(BUY_AMOUNT)-Decimal(GAS_COST))/Decimal(BUY_AMOUNT)*Decimal(100)
                            glb_daily_pnl = (glb_daily_pnl[0], glb_daily_pnl[1] + pnl)
                            logging.warning(f"MAIN update PnL to value {round(glb_daily_pnl[1],6)} upon liquidation failed")

                            # decrease the buy-amount to reduce risk exposure
                            if glb_daily_pnl[1]<-100 and BUY_AMOUNT-AMOUNT_CHANGE_STEP>=MIN_BUY_AMOUNT:
                                BUY_AMOUNT-=AMOUNT_CHANGE_STEP
                                glb_daily_pnl = (glb_daily_pnl[0], 0)
                                logging.warning(f"MAIN decrease buy-amount to {BUY_AMOUNT} caused by PnL fall below -100, reset PnL")


                        report_broker.put(ReportData(
                            type=ReportDataType.BLACKLIST_ADDED,
                            data=[report.pair.creator]
                        ))
                        logging.warning(f"MAIN add {report.pair.creator} to blacklist")

    async def handle_control_order():
        global glb_lock
        global glb_inventory

        async def handle_pending_positions(positions):
            with glb_lock:
                for pos in positions: 
                    glb_inventory.append(pos)
                    logging.warning(f"MAIN append {pos} to inventory upon bootstrap process")

        while True:
            order = await control_receiver.coro_get()

            if order is not None and isinstance(order, ControlOrder):
                if order.type==ControlOrderType.PENDING_POSITIONS:
                    await handle_pending_positions(order.data)

    # control_receiver.put(ReportData(
    #     type=ReportDataType.BLACKLIST_BOOTSTRAP,
    #     data=[14.95,19.95]
    # ))

    # watching_broker.put(BlockData(
    #     block_number=1,
    #     block_timestamp=1,
    #     base_fee=5000,
    #     gas_used=10**6,
    #     gas_limit=10**6,
    #     pairs=[Pair(
    #         token='0xfoo',
    #         token_index=1,
    #         address='0xbar',
    #         reserve_token=1,
    #         reserve_eth=14.95,
    #     )]
    # ))

    await asyncio.gather(watching_process(watching_broker, watching_notifier),
                        strategy(watching_broker, execution_broker, report_broker, watching_notifier,),
                        handle_execution_report(),
                        reporter.run(),
                        handle_control_order(),
                        )
def signal_handler(signum, frame):
    print("Received termination signal. Shutting down...")
    # Add any cleanup code here
    sys.exit(0)

if __name__=="__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    asyncio.run(main())