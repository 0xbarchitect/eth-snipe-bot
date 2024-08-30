import os
from web3 import Web3
import json
from typing import Any, Dict
import random
from decimal import Decimal
import pytz
from datetime import datetime
import eth_utils

def load_contract_bin(contract_path: str) -> bytes:
    with open(contract_path, 'r') as readfile:
        hexstring = readfile.readline()
    return bytes.fromhex(hexstring)

def load_router_contract(contract_path, factory_address, wavax_address) -> bytes:
    with open(contract_path, 'r') as readfile:
        hexstring = readfile.readline()

    #print(f"hexstr {hexstring[:len(hexstring)-128]}")

    newcode = f"{hexstring[:len(hexstring)-128]}{encode_address(factory_address)}{encode_address(wavax_address)}"
    return bytes.fromhex(newcode)

def load_abi(abi_path: str):
    return json.load(open(abi_path, 'r'))

def func_selector(signature: str) -> str:
    return (Web3.keccak(text=signature)[0:4]).hex()[2:]

def encode_uint(num: int) -> str:
    encoded = hex(num)[2:]
    return ("0" * (64 - len(encoded))) + encoded

def encode_address(address: str) -> str:
    return f'{"0" * 24}{address[2:]}'

def decode_address(bytestr) -> str:
    return f"0x{Web3.to_hex(bytestr)[26:]}"

def decode_int(bytestr, currency) -> int:
    return Web3.from_wei(int.from_bytes(bytestr, 'big'), currency)

def convert_hex_to_int(hex_str) -> int:
    return Web3.to_int(hexstr=Web3.to_hex(hexstr=hex_str))

def decode_pair_reserves(bytestr):
    hexval = Web3.to_hex(bytestr)
    
    if len(hexval[2:]) != 192: # must be 96 bytes
        raise Exception("invalid reserves")
        
    return convert_hex_to_int(hexval[2:66]),convert_hex_to_int(hexval[66:130]),convert_hex_to_int(hexval[130:])

def calculate_amount_out(reserveIn, reserveOut, amountIn):
    return reserveOut - (reserveIn * reserveOut)/(reserveIn + amountIn)

def calculate_amount_in(reserveIn, reserveOut, amountOut):
    return (reserveIn * reserveOut)/(reserveOut - amountOut) - reserveIn

def calculate_price(reserve_token, reserve_eth):
    if reserve_token != 0 and reserve_eth != 0:
        return Decimal(reserve_eth)/Decimal(reserve_token)
    return 0

def calculate_next_block_base_fee(base_fee, gas_used, gas_limit):
    target_gas_used = gas_limit / 2
    target_gas_used = 1 if target_gas_used == 0 else target_gas_used

    if gas_used > target_gas_used:
        new_base_fee = base_fee + ((base_fee * (gas_used - target_gas_used)) / target_gas_used) / 8
    else:
        new_base_fee = base_fee - ((base_fee * (target_gas_used - gas_used)) / target_gas_used) / 8

    return Decimal(int(new_base_fee + random.randint(0, 9)))

def sort_tokens(tokenA, tokenB):
    return (tokenA, tokenB) if Web3.to_int(hexstr=tokenA) < Web3.to_int(hexstr=tokenB) else (tokenB, tokenA)

def convert_tz_aware(dt_obj):
    dt_obj.tzinfo = pytz.UTC

def shorten_address(address):
    return f"{address[0:5]}..{address[len(address)-4:]}"

def calculate_balance_storage_index(address, index):
    return Web3.keccak(
        hexstr=(
            eth_utils.remove_0x_prefix(address).rjust(64, '0')
            +
            eth_utils.remove_0x_prefix(hex(index)).rjust(64,'0')
        )
    )

def calculate_allowance_storage_index(owner, spender, index):
    return Web3.keccak(
        hexstr=(
            eth_utils.remove_0x_prefix(spender).rjust(64, "0")
            + eth_utils.remove_0x_prefix(
                Web3.keccak(
                hexstr=(
                    eth_utils.remove_0x_prefix(owner).rjust(64, "0")
                    + 
                    eth_utils.remove_0x_prefix(hex(index)).rjust(64,'0')
                )
            ).hex())   
        )
    )

def rpad_int(amount):
    return "0x" + eth_utils.remove_0x_prefix(hex(amount)).rjust(64,'0')

def calculate_expect_pnl(buy_amount, min_buy_amount, min_expected_pnl, rr_ratio):
    return Decimal(min_buy_amount*min_expected_pnl/100 + (buy_amount-min_buy_amount)*rr_ratio)/Decimal(buy_amount)*Decimal(100)

def get_hour_in_vntz(dt: datetime):
    from zoneinfo import ZoneInfo
    dt=dt.astimezone(ZoneInfo('Asia/Ho_Chi_Minh'))
    return int(dt.strftime('%H'))

def determine_epoch(epoch_time_hour):
    return round(Decimal(get_hour_in_vntz(datetime.now())) / Decimal(epoch_time_hour))