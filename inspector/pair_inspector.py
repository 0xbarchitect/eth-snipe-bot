import asyncio
import os
import logging
import time
import datetime
from decimal import Decimal
import requests
import concurrent.futures

from web3 import Web3
from uniswap_universal_router_decoder import FunctionRecipient, RouterCodec
import eth_abi

import sys # for testing
sys.path.append('..')

from library import Singleton
from helpers.decorators import timer_decorator, async_timer_decorator
from helpers.utils import load_contract_bin, encode_address, encode_uint, func_selector, \
                            decode_address, decode_pair_reserves, decode_int, load_router_contract, \
                            load_abi, calculate_next_block_base_fee, calculate_balance_storage_index, rpad_int, \
                            calculate_allowance_storage_index
from helpers import constants
from data import Pair, MaliciousPair, InspectionResult, SimulationResult
from inspector import RevmSimulator, EthCallSimulator

# django
import django
from django.utils.timezone import make_aware
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin.settings")
django.setup()
import console.models

STATUS_CODE_SUCCESS=200
PAGE_SIZE=100
MM_TX_AMOUNT_THRESHOLD=0.01
CREATOR_TX_HISTORY_PAGE_SIZE=500

SIMULATION_AMOUNT=0.003
SLIPPAGE_MIN_THRESHOLD = 30 # in basis points
SLIPPAGE_MAX_THRESHOLD = 200 # in basis points

RESERVE_ETH_MIN_THRESHOLD=float(os.environ.get('RESERVE_ETH_MIN_THRESHOLD'))
RESERVE_ETH_MAX_THRESHOLD=float(os.environ.get('RESERVE_ETH_MAX_THRESHOLD'))
CONTRACT_VERIFIED_REQUIRED=int(os.environ.get('CONTRACT_VERIFIED_REQUIRED'))
ROGUE_CREATOR_FROZEN_SECONDS=int(os.environ.get('ROGUE_CREATOR_FROZEN_SECONDS'))

HOLD_MAX_DURATION_SECONDS=int(os.environ.get('HOLD_MAX_DURATION_SECONDS'))
MAX_INSPECT_ATTEMPTS=int(os.environ.get('MAX_INSPECT_ATTEMPTS'))
INSPECT_INTERVAL_SECONDS=int(os.environ.get('INSPECT_INTERVAL_SECONDS'))

from enum import IntEnum

class PairInspector(metaclass=Singleton):
    def __init__(self,
                 http_url,
                 api_keys,
                 etherscan_api_url,
                 signer, 
                 router, 
                 weth,
                 bot,
                 pair_abi,
                 weth_abi,
                 bot_abi,
                 ) -> None:
        
        self.http_url = http_url
        self.w3 = Web3(Web3.HTTPProvider(http_url))
        self.api_keys = api_keys.split(',')
        self.etherscan_api_url = etherscan_api_url

        self.signer = signer
        self.router = router
        self.weth = weth
        self.bot = bot

        self.pair_abi = pair_abi
        self.weth_abi = weth_abi
        self.bot_abi = bot_abi
        self.counter = 0

        self.simulator = EthCallSimulator(
            http_url=http_url,
            signer=signer,
            bot=bot,
        )

    @timer_decorator
    def is_contract_verified(self, pair: Pair) -> False:
        def source_code_is_not_malicious(source):
            if 'family' in source:
                return True
            return False

        if pair.contract_verified:
            return True
        
        r=requests.get(f"{self.etherscan_api_url}/api?module=contract&action=getsourcecode&address={pair.token}&apikey={self.select_api_key()}")
        if r.status_code==STATUS_CODE_SUCCESS:
            res=r.json()
            logging.debug(f"INSPECTOR GetSourceCode result {res}")

            if int(res['status'])==1 and len(res['result'][0].get('Library',''))==0:
                if CONTRACT_VERIFIED_REQUIRED==1:
                    return True if len(res['result'][0].get('SourceCode',''))>0 and len(res['result'][0].get('ContractName'))>0 and not source_code_is_not_malicious(res['result'][0]['SourceCode']) else False
                return True
        else:
            logging.error(f"INSPECTOR EtherscanAPI GetSourceCode error:: {r.status_code}")
                
        return False
        
    @timer_decorator
    def is_creator_call_contract(self, pair, from_block, to_block):
        txlist = self.get_txlist(pair.token, from_block, to_block)
        
        if int(txlist['status'])==constants.TX_SUCCESS_STATUS and len(txlist['result'])>0:
            txs = [tx for tx in txlist['result'] if int(tx['txreceipt_status'])==constants.TX_SUCCESS_STATUS and tx['to'].lower()==pair.token.lower() and tx['methodId'] not in [constants.RENOUNCE_OWNERSHIP_METHOD_ID, constants.APPROVE_METHOD_ID]]
            if len(txs)>0:
                logging.warning(f"INSPECTOR Pair {pair.address} detected malicious due to abnormal incoming txs {txs}")
            return len(txs)
            
        return 0
    
    def get_txlist(self, contract, start_block, end_block, page_size=100, sort='desc'):
        r=requests.get(f"{self.etherscan_api_url}/api?module=account&action=txlist&address={contract}&startblock={start_block}&endblock={end_block}&page=1&offset={page_size}&sort={sort}&apikey={self.select_api_key()}")
        if r.status_code==STATUS_CODE_SUCCESS:
            res=r.json()
            return res
        return None
    
    def select_api_key(self):
        self.counter+=1
        return self.api_keys[self.counter % len(self.api_keys)]
            
    @timer_decorator
    def number_tx_mm(self, pair, from_block, to_block) -> 0:
        contract=self.w3.eth.contract(address=Web3.to_checksum_address(pair.address),abi=self.pair_abi)
        logs = contract.events.Swap().get_logs(
                fromBlock = from_block,
                toBlock = to_block,
            )
        if logs != ():
            txs=[log for log in logs if (Web3.from_wei(log['args']['amount0In'], 'ether')>MM_TX_AMOUNT_THRESHOLD and pair.token_index==1) or (Web3.from_wei(log['args']['amount1In'], 'ether')>MM_TX_AMOUNT_THRESHOLD and pair.token_index==0)]
            return len(txs)
        
        return 0
        
    @timer_decorator
    def is_malicious(self, pair, block_number, is_initial=False) -> MaliciousPair:
        blacklist = console.models.BlackList.objects.filter(address=pair.creator.lower()).filter(frozen_at__gte=make_aware(datetime.datetime.now()-datetime.timedelta(seconds=ROGUE_CREATOR_FROZEN_SECONDS))).filter(created_at__gte=make_aware(datetime.datetime.now() - datetime.timedelta(days=90))).first()
        if blacklist is not None:
            logging.warning(f"INSPECTOR pair {pair.address} is blacklisted due to rogue creator")
            return MaliciousPair.CREATOR_BLACKLISTED
        
        # check malicious tx
        try:
            r=requests.get(f"{self.etherscan_api_url}/api?module=contract&action=getcontractcreation&contractaddresses={pair.token}&apikey={self.select_api_key()}")
            if r.status_code==STATUS_CODE_SUCCESS:
                res=r.json()
                if int(res['status'])==1 and res['result'][0]['txHash'] is not None:
                    tx_receipt = self.w3.eth.get_transaction_receipt(res['result'][0]['txHash'])
                    txlist = self.get_txlist(pair.token, tx_receipt['blockNumber'], block_number)
                    if int(txlist['status'])==constants.TX_SUCCESS_STATUS and txlist['result'] is not None:
                        for tx in txlist['result']:
                            if int(tx['txreceipt_status'])==constants.TX_SUCCESS_STATUS and tx['to'].lower()==pair.token.lower() and tx['methodId'] not in [constants.APPROVE_METHOD_ID, constants.RENOUNCE_OWNERSHIP_METHOD_ID, constants.TRANSFER_METHOD_ID, constants.TRANSFER_NATIVE_METHOD_ID]:
                                logging.warning(f"INSPECTOR pair {pair.address} detected malicious due to abnormal incoming tx {tx}")
                                return MaliciousPair.MALICIOUS_TX_IN
            else:
                logging.error(f"INSPECTOR GetContractCreation error {r.status_code}")
                return MaliciousPair.UNVERIFIED
        except Exception as e:
            logging.error(f"INSPECTOR IsMalicious check error:: {e}")
            return MaliciousPair.UNVERIFIED

        return MaliciousPair.UNMALICIOUS
    
    @timer_decorator
    def inspect_pair(self, pair: Pair, block_number, is_initial=False) -> InspectionResult:
        from_block=pair.last_inspected_block+1 if pair.last_inspected_block>0 else block_number

        result = InspectionResult(
            pair=pair,
            from_block=from_block,
            to_block=block_number,
        )

        if pair.reserve_eth>=RESERVE_ETH_MIN_THRESHOLD and pair.reserve_eth<=RESERVE_ETH_MAX_THRESHOLD:
            result.reserve_inrange=True

        if is_initial and not result.reserve_inrange:
            return result        

        result.is_malicious=self.is_malicious(pair, block_number, is_initial)
        if result.is_malicious != MaliciousPair.UNMALICIOUS:
            return result

        # TODO: try to verify multiple times
        result.contract_verified=self.is_contract_verified(pair)
        #if not result.contract_verified:
            #return result
        
        if not is_initial:
            result.is_creator_call_contract=self.is_creator_call_contract(pair,from_block,block_number)
            if result.is_creator_call_contract>0:                
                return result
        
            result.number_tx_mm=self.number_tx_mm(pair,from_block,block_number)

        simulation_result = self.simulator.inspect_pair(pair, SIMULATION_AMOUNT)
        if simulation_result is not None:
            if simulation_result.slippage > SLIPPAGE_MIN_THRESHOLD and simulation_result.slippage < SLIPPAGE_MAX_THRESHOLD:
                result.simulation_result=simulation_result
            else:
                logging.warning(f"INSPECTOR simulation result rejected due to abnormal slippage {simulation_result.slippage}")

        return result
    
    @timer_decorator
    def inspect_batch(self, pairs, block_number, is_initial=False):
        results = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_pair = {executor.submit(self.inspect_pair,pair,block_number,is_initial): pair.address for pair in pairs}
            for future in concurrent.futures.as_completed(future_to_pair):
                pair = future_to_pair[future]
                try:
                    result = future.result()
                    logging.warning(f"INSPECTOR inspect pair {pair} {result}")
                    results.append(result)
                except Exception as e:
                    logging.error(f"INSPECTOR inspect pair {pair} error {e}")

        return results
        
if __name__=="__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    PAIR_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/UniV2Pair.abi.json")
    WETH_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/WETH.abi.json")
    BOT_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/SnipeBot.abi.json")

    inspector = PairInspector(
        http_url=os.environ.get('HTTPS_URL'),
        api_keys=os.environ.get('BASESCAN_API_KEYS'),
        etherscan_api_url=os.environ.get('ETHERSCAN_API_URL'),
        signer=Web3.to_checksum_address(os.environ.get('MANAGER_ADDRESS')),
        bot=Web3.to_checksum_address(os.environ.get('INSPECTOR_BOT')),
        router=Web3.to_checksum_address(os.environ.get('ROUTER_ADDRESS')),
        weth=Web3.to_checksum_address(os.environ.get('WETH_ADDRESS')),
        pair_abi=PAIR_ABI,
        weth_abi=WETH_ABI,
        bot_abi=BOT_ABI,
    )

    pair = Pair(
        address="0xc6a68497790cfd61f8b8c0d93e3ad67b82957d25",
        token="0xff00bd801eacaa8b11101fde025fdc81d8dfe5b0",
        token_index=1,
        creator="0x1e9c7f4a0f3c2a0e167f059bd4e8cbf49af0659c",
        reserve_eth=1,
        reserve_token=0,
        created_at=0,
        inspect_attempts=1,
        contract_verified=False,
        number_tx_mm=0,
        last_inspected_block=0, # is the created_block as well
    )

    #print("contract verified") if inspector.is_contract_verified(pair) else print(f"contract unverified")
    #print(f"number called {inspector.is_creator_call_contract(pair, 41665828, 41666241)}")
    #print(f"number mm_tx {inspector.number_tx_mm(pair, 41665828, 41665884)}")
    #print(f"is malicious {inspector.is_malicious(pair, 41665828, is_initial=True)}")

    inspector.inspect_batch([pair], 20669433, is_initial=True)