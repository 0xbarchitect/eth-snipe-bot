import asyncio
import os
import logging
import time
from decimal import Decimal

from web3 import Web3
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
    def __init__(self, http_url, signer, bot):
        logging.debug(f"start simulation...")

        self.w3 = Web3(Web3.HTTPProvider(http_url))
        self.signer = signer
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
            logging.info(f"SIMULATOR Buy result {resultBuy}")

            if resultBuy is None:
                return None

            assert len(resultBuy[0]) == 2
            assert resultBuy[0][0] == Web3.to_wei(amount, 'ether')

            # sell
            resultSell = self.sell(token, Web3.from_wei(resultBuy[0][1], 'ether'))
            logging.info(f"SIMULATOR Sell result {resultSell}")

            if resultSell is None:
                return None

            assert len(resultSell[0]) == 2
            assert resultSell[0][0] == resultBuy[0][1]

            amount_out = Web3.from_wei(resultSell[0][1], 'ether')
            slippage = (Decimal(amount) - Decimal(amount_out))/Decimal(amount)*Decimal(10000)
            amount_token = Web3.from_wei(resultBuy[0][1], 'ether')
            
            return (amount, amount_out, slippage, amount_token)
        except Exception as e:
            logging.error(f"SIMULATOR inspect {token} failed with error {e}")
        
        return None
    
    def buy(self, token, amount, signer=None, bot=None) -> None:
        try:
            signer = self.signer if signer is None else signer
            bot = self.bot if bot is None else bot
            token = Web3.to_checksum_address(token)

            state_diff = {
                signer: {
                    'balance': hex(10**18) # 1 ETH
                }
            }
            
            result = self.w3.eth.call({
                'from': signer,
                'to': bot,
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
            signer = self.signer if signer is None else signer
            bot = self.bot if bot is None else bot

            balance_slot_index = self.determine_balance_slot_index(token)
            logging.info(f"SIMULATOR Balance slot index {balance_slot_index}")

            if balance_slot_index is not None:
                storage_index = calculate_balance_storage_index(bot, balance_slot_index)
                logging.debug(f"SIMULATOR Storage index {storage_index.hex()}")

                result = self.w3.eth.call({
                    'from': signer,
                    'to': bot,
                    'data': bytes.fromhex(
                        func_selector('sell(address,address,uint256)') + encode_address(token) + encode_address(signer) + encode_uint(int(time.time()) + 1000)
                    )
                }, 'latest', self.create_state_diff(token, storage_index, Web3.to_wei(amount, 'ether')))

                resultSell = eth_abi.decode(['uint[]'], result)
                return resultSell
        except Exception as e:
            logging.error(f"SIMULATOR Sell error {e}")

        
    def determine_balance_slot_index(self, token):
        fake_amount = 10**27 # 1B
        fake_owner = self.signer

        for idx in range(9):
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
                    bot=Web3.to_checksum_address(os.environ.get('INSPECTOR_BOT')),
                    )
    
    result=simulator.inspect_pair(Pair(
        address='0x1bf00256979d45402dd2340232da4ca2ba8531cc',
        token='0x22a0005b11e76128239401f237c512962b32a38b',
        token_index=0,
        reserve_token=0,
        reserve_eth=0
    ), 0.001, swap=True)

    logging.warning(f"Simulation result {result}")
