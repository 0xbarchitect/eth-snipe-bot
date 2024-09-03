import os
from decimal import Decimal

class Pair:
    def __init__(self, token, token_index, address, reserve_token=0, reserve_eth=0, created_at=0, inspect_attempts=0, creator=None, contract_verified=False, number_tx_mm=0, last_inspected_block=0) -> None:
        self.token = token
        self.token_index = token_index
        self.address = address
        self.reserve_token = reserve_token
        self.reserve_eth = reserve_eth
        self.created_at = created_at
        self.inspect_attempts = inspect_attempts
        self.creator = creator
        self.contract_verified = contract_verified
        self.number_tx_mm = number_tx_mm
        self.last_inspected_block = last_inspected_block

    def price(self):
        if self.reserve_token != 0 and self.reserve_eth != 0:
            return Decimal(self.reserve_eth) / Decimal(self.reserve_token)
        return 0

    def  __str__(self) -> str:
        return f"""
        Pair {self.address} Token {self.token} TokenIndex {self.token_index}
        Creator {self.creator} ReserveToken {self.reserve_token} ReserveEth {self.reserve_eth}
        ContractVerified {self.contract_verified} NumberTxMM {self.number_tx_mm} InspectAttempts {self.inspect_attempts} LastInspectedBlock {self.last_inspected_block}
        """

class BlockData:
    def __init__(self, block_number, block_timestamp, base_fee, gas_used, gas_limit, pairs=[], inventory=[], watchlist=[]) -> None:
        self.block_number = block_number
        self.block_timestamp = block_timestamp
        self.base_fee = base_fee
        self.gas_used = gas_used
        self.gas_limit = gas_limit
        self.pairs = pairs
        self.inventory = inventory
        self.watchlist = watchlist

    def __str__(self) -> str:
        return f"""
        Block #{self.block_number} timestamp {self.block_timestamp} baseFee {self.base_fee} gasUsed {self.gas_used} gasLimit {self.gas_limit}
        Pairs created {len(self.pairs)} Inventory {len(self.inventory)} Watchlist {len(self.watchlist)}
        """

class Position:
    def __init__(self, pair, amount, buy_price, start_time, pnl=0, signer=None, bot=None, amount_in=None, is_paper=False) -> None:
        self.pair = pair
        self.amount = amount
        self.buy_price = buy_price
        self.start_time = start_time
        self.pnl = pnl
        self.signer = signer
        self.bot = bot
        self.amount_in = amount_in
        self.is_paper = is_paper

    def __str__(self) -> str:
        return f"Position {self.pair.address} amount {self.amount} buyPrice {self.buy_price} startTime {self.start_time} signer {self.signer} bot {self.bot} pnl {self.pnl} isPaper {self.is_paper}"
    

class ExecutionOrder:
    def __init__(self, block_number, block_timestamp, pair: Pair, amount_in, amount_out_min, is_buy, signer=None, bot=None, is_paper=False, position: Position=None) -> None:
        self.block_number = block_number
        self.block_timestamp = block_timestamp
        self.pair = pair
        self.amount_in = amount_in
        self.amount_out_min = amount_out_min
        self.is_buy = is_buy
        self.signer = signer
        self.bot = bot
        self.is_paper = is_paper
        self.position = position

    def __str__(self) -> str:
        return f"ExecutionOrder Block #{self.block_number} Pair {self.pair.address} AmountIn {self.amount_in} AmountOutMin {self.amount_out_min} Signer {self.signer} Bot {self.bot} IsBuy {self.is_buy} IsPaper {self.is_paper}"
    
class ExecutionAck:
    def __init__(self, lead_block, block_number, tx_hash, tx_status, pair: Pair, amount_in, amount_out, is_buy, signer=None, bot=None, is_paper=False) -> None:
        self.lead_block = lead_block
        self.block_number = block_number
        self.tx_hash = tx_hash
        self.tx_status = tx_status
        self.pair = pair
        self.amount_in = amount_in
        self.amount_out = amount_out
        self.is_buy = is_buy
        self.signer = signer
        self.bot = bot
        self.is_paper = is_paper

    def __str__(self) -> str:
        return f"""
        ExecutionAck lead #{self.lead_block} realized #{self.block_number} Tx {self.tx_hash} STATUS {self.tx_status}
        Pair {self.pair.address} AmountIn {self.amount_in} AmountOut {self.amount_out} Signer {self.signer} Bot {self.bot} IsBuy {self.is_buy} IsPaper {self.is_paper}
        """
from enum import IntEnum

class ReportDataType(IntEnum):
    BLOCK = 0
    EXECUTION = 1
    WATCHLIST_ADDED = 2
    WATCHLIST_REMOVED = 3
    BLACKLIST_BOOTSTRAP = 4
    BLACKLIST_ADDED = 5

class ReportData:
    def __init__(self, type, data) -> None:
        self.type = type
        self.data = data

    def __str__(self) -> str:
        return f"""
        Report type #{self.type} data {self.data}
        """

class Bot:
    def __init__(self, address, owner, deployed_at=0, number_used=0, is_failed=False, is_holding=False) -> None:
        self.address = address
        self.owner = owner
        self.deployed_at = deployed_at
        self.number_used = number_used
        self.is_failed = is_failed
        self.is_holding = is_holding

    def __str__(self) -> str:
        return f"""
        Bot {self.address} Owner {self.owner} DeployedAt {self.deployed_at}
        NumberUsed {self.number_used} IsFailed {self.is_failed} IsHolding {self.is_holding}
        """
    
class W3Account:
    def __init__(self, w3_account, private_key, bot:Bot = None) -> None:
        self.w3_account = w3_account
        self.private_key = private_key
        self.bot = bot

class SimulationResult:
    def __init__(self, pair, amount_in, amount_out, slippage, amount_token=0) -> None:
        self.pair = pair
        self.amount_in = amount_in
        self.amount_out = amount_out
        self.slippage = slippage
        self.amount_token = amount_token

    def __str__(self) -> str:
        return f"Simulation result {self.pair.address} slippage {self.slippage} amountIn {self.amount_in} amountOut {self.amount_out} amountToken {self.amount_token}"
    
class FilterLogsType(IntEnum):
    PAIR_CREATED = 0
    SYNC = 1
    SWAP = 2

class FilterLogs:
    def __init__(self, type: FilterLogsType, data) -> None:
        self.type = type
        self.data = data
    
    def __str__(self) -> str:
        return f"FilterLogs type {self.type} data {self.data}"
     
class TxStatus(IntEnum):
    FAILED = 0
    SUCCESS = 1

class MaliciousPair(IntEnum):
    UNMALICIOUS=0
    CREATOR_BLACKLISTED=1
    CREATOR_RUGGED=2
    UNVERIFIED=3
    MALICIOUS_TX_IN=4

class InspectionResult:
    def __init__(self, pair: Pair, from_block, to_block, reserve_inrange=False, simulation_result=None, is_malicious=MaliciousPair.UNMALICIOUS, contract_verified=False, is_creator_call_contract=0, number_tx_mm=0) -> None:
        self.pair = pair
        self.from_block = from_block
        self.to_block = to_block

        self.reserve_inrange = reserve_inrange
        self.simulation_result = simulation_result
        self.is_malicious = is_malicious
        self.contract_verified = contract_verified
        self.is_creator_call_contract = is_creator_call_contract
        self.number_tx_mm = number_tx_mm

    def __str__(self) -> str:
        return f"""
        Inspection result Pair {self.pair.address} fromBlock {self.from_block} toBlock {self.to_block}
        ReserveInrange {self.reserve_inrange} IsMalicious {self.is_malicious} ContractVerified {self.contract_verified}
        CreatorCallContract {self.is_creator_call_contract} NumberTxMM {self.number_tx_mm}
        SimulationResult {self.simulation_result}
        """

class BotCreationOrder:
    def __init__(self, owner, retry_times=0) -> None:
        self.owner = owner
        self.retry_times = retry_times

    def __str__(self) -> str:
        return f"BotCreationOrder owner {self.owner} retryTimes {self.retry_times}"
    
class BotUpdateOrder:
    def __init__(self, bot:Bot, execution_ack: ExecutionAck) -> None:
        self.bot = bot
        self.execution_ack = execution_ack

    def __str__(self) -> str:
        return f"UpdateBotOrder for {self.bot.address} with execution ack {self.execution_ack.tx_hash}"
    
class ControlOrderType(IntEnum):
    PENDING_POSITIONS=0

class ControlOrder:
    def __init__(self, type: ControlOrderType, data) -> None:
        self.type = type
        self.data = data

    def __str__(self) -> str:
        return f"ControlOrder Type{self.type} Data {self.data}"