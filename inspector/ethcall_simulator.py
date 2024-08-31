import asyncio
import os
import logging
import time
from decimal import Decimal

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

from data import SimulationResult, Pair

class EthCallSimulator:
    @timer_decorator
    def __init__(self, 
                 http_url, 
                 signer, 
                 router_address, 
                 weth,
                 bot,
                 pair_abi,
                 bot_abi,
                 ):
        logging.debug(f"start simulation...")

        self.http_url = http_url
        self.signer = signer

        self.router_address = router_address
        self.weth = weth

        self.w3 = Web3(Web3.HTTPProvider(http_url))
        self.pair_abi = pair_abi
        #self.bot = self.w3.eth.contract(address=bot, abi=bot_abi)
        self.bot = bot

    @timer_decorator
    def inspect_token_by_transfer(self, token, amount):
        try:
            balance_index = calculate_balance_storage_index(self.signer,0)
            allowance_index = calculate_allowance_storage_index(self.signer, self.bot,1)

            result = self.w3.eth.call({
                'from': self.signer,
                'to': self.bot,
                'data': bytes.fromhex(
                    func_selector('inspect_transfer(address,uint256)') + encode_address(token) + encode_uint(Web3.to_wei(amount, 'ether'))
                )
            }, 'latest', {
                token: {
                    'stateDiff': {
                        balance_index.hex(): hex(Web3.to_wei(amount, 'ether')),
                        allowance_index.hex(): hex(Web3.to_wei(amount, 'ether')),
                    }
                }
            })

            logging.info(f"inspect_transfer result {Web3.from_wei(Web3.to_int(result), 'ether')}")

            amount_out=Web3.from_wei(Web3.to_int(result), 'ether')
            slippage=(Decimal(amount_out)-Decimal(amount))/Decimal(amount)*Decimal(100)

            return (amount, amount_out, slippage, amount)
        except Exception as e:
            logging.error(f"inspect token {token} failed with error {e}")
            return None
        
    @timer_decorator
    def inspect_token_by_swap(self, token, amount) -> None:
        try:
            # buy
            resultBuy = self.buy(token, amount)

            assert len(resultBuy[0]) == 2
            assert resultBuy[0][0] == Web3.to_wei(amount, 'ether')

            logging.info(f"SIMULATOR Buy result {resultBuy}")

            # sell
            resultSell = self.sell(token, resultBuy[0][1])

            assert len(resultSell[0]) == 2
            assert resultSell[0][0] == resultBuy[0][1]

            logging.info(f"SIMULATOR Sell result {resultSell}")

            amount_out = Web3.from_wei(resultSell[0][1], 'ether')
            slippage = (Decimal(amount) - Decimal(amount_out))/Decimal(amount)*Decimal(10000)
            amount_token = Web3.from_wei(resultBuy[0][1], 'ether')
            
            return (amount, amount_out, slippage, amount_token)
        except Exception as e:
            logging.error(f"SIMULATOR inspect {token} failed with error {e}")
        
        return None
    
    def buy(self, token, amount, signer=None, bot=None) -> None:
        try:
            state_diff = {
                self.signer: {
                    'balance': hex(10**18) # 1 ETH
                }
            }
            token = Web3.to_checksum_address(token)
            result = self.w3.eth.call({
                'from': self.signer if signer is None else signer,
                'to': self.bot if bot is None else bot,
                'value': Web3.to_wei(amount, 'ether'),
                'data': bytes.fromhex(
                    func_selector('buy(address,uint256)') + encode_address(token) + encode_uint(int(time.time()) + 1000)
                )
            }, 'latest', state_diff)

            resultBuy = eth_abi.decode(['uint[]'], result)
            return resultBuy
        except Exception as e:
            logging.error(f"SIMULATOR Buy error {e}")

    def sell(self, token, amount, signer=None, bot=None) -> None:
        try:
            balance_slot_index = self.determine_balance_slot_index(token)
            logging.debug(f"SIMULATOR Balance slot index {balance_slot_index}")

            if balance_slot_index is not None:
                storage_index = calculate_balance_storage_index(self.bot, balance_slot_index)

                result = self.w3.eth.call({
                    'from': self.signer if signer is None else signer,
                    'to': self.bot if bot is None else bot,
                    'data': bytes.fromhex(
                        func_selector('sell(address,address,uint256)') + encode_address(token) + encode_address(self.signer) + encode_uint(int(time.time()) + 1000)
                    )
                }, 'latest', self.create_state_diff(token, storage_index, amount))

                resultSell = eth_abi.decode(['uint[]'], result)
                return resultSell
        except Exception as e:
            logging.error(f"SIMULATOR Sell error {e}")

        
    def determine_balance_slot_index(self, token):
        fake_amount = 10**27 # 1B
        fake_owner = self.signer
        for idx in [0,1]:
            storage_index = calculate_balance_storage_index(fake_owner, idx)

            result = self.w3.eth.call({
                'from': self.signer,
                'to': Web3.to_checksum_address(token),
                'data': bytes.fromhex(
                    func_selector('balanceOf(address)') + encode_address(fake_owner)
                )
            }, 'latest', self.create_state_diff(token, storage_index, fake_amount))
            logging.debug(f"index {idx} get balance result fake {eth_abi.decode(['uint256'], result)}")

            decoded = eth_abi.decode(['uint256'], result)
            if decoded[0] == fake_amount:
                return idx

        return None

    def create_state_diff(self, token, storage_index, amount):
        return {
                Web3.to_checksum_address(token): {
                    'stateDiff': {
                        storage_index.hex(): '0x'+hex(amount)[2:].zfill(64),
                    }
                }
            }
        
    def inspect_pair(self, pair: Pair, amount, swap=True) -> None:
        if swap is False:
            result = self.inspect_token_by_transfer(pair.token, amount)
        else:
            result = self.inspect_token_by_swap(pair.token, amount)

        if result is not None:
            return SimulationResult(
                pair=pair,
                amount_in=result[0],
                amount_out=result[1],
                slippage=result[2],
                amount_token=result[3],
                )
        
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    PAIR_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/UniV2Pair.abi.json")
    BOT_ABI = load_abi(f"{os.path.dirname(__file__)}/../contracts/abis/SnipeBot.abi.json")

    ETH_BALANCE = 1000
    GAS_LIMIT = 200*10**3
    FEE_BPS = 25

    simulator = EthCallSimulator(
                    http_url=os.environ.get('HTTPS_URL'),
                    signer=Web3.to_checksum_address(os.environ.get('MANAGER_ADDRESS')),
                    router_address=Web3.to_checksum_address(os.environ.get('ROUTER_ADDRESS')),
                    weth=Web3.to_checksum_address(os.environ.get('WETH_ADDRESS')),
                    bot=Web3.to_checksum_address(os.environ.get('INSPECTOR_BOT')),
                    pair_abi=PAIR_ABI,
                    bot_abi=BOT_ABI,
                    )
    
    result=simulator.inspect_pair(Pair(
        address='0x4f73b3982def9b92d021defe97a6a8f03e3ae573',
        token='0x26fd4c3600b12eae0b8caaaa74590e67222bf308',
        token_index=0,
        reserve_token=0,
        reserve_eth=0
    ), 0.1, swap=True)

    logging.warning(f"Simulation result {result}")
