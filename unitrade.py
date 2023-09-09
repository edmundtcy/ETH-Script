import os
import json
import secrets
import requests
import threading
import numpy as np
from web3 import Web3
from datetime import datetime
from eth_account import Account

def key_initizer():
    #Try to open credentials.json
    try:
        with open('credentials.json') as json_file:
            keys = json.load(json_file)
            print("Credentials.json loaded")
        return keys
    except:
        #If credentials.json does not exist, create it
        print("Credentials.json not found, creating new file")
        private_key = input("Please enter your private key or type 'n' to create new wallet: ")
        etherscan_key = input("Please enter your etherscan key: ")
        infura_key = input("Please enter your quicknode key: ")
        if private_key == 'n':
            private_key = secrets.token_hex(32)
            print("New wallet created with private key: " + private_key)
        keys = {
            "private_key": private_key,
            "etherscan_key": etherscan_key,
            "infura_key": infura_key
        }
        with open('credentials.json', 'w') as outfile:
            json.dump(keys, outfile)
        print("key file created as Credentials.json")
        return keys

def bot_config():
    if os.path.isfile('config.json'):
        with open('config.json') as json_file:
            config = json.load(json_file)
    else:
        config = {}

    with open('config.json', 'w') as outfile:
        json.dump(config, outfile)

def fetch_abi(contract_address, chain_id=1):
    #Get Contract ABI with Etherscan API
    api_key = ETHERSCAN_KEY
    if chain_id == 1:
        url = 'https://api.etherscan.io/api'
    elif chain_id == 5:
        url = 'https://api-goerli.etherscan.io/api'
    params = {
        'module': 'contract',
        'action': 'getabi',
        'address': contract_address,
        'apikey': api_key
    }
    response = requests.get(url, params=params)
    data = response.json()
    if data['status'] != '1':
        print("Error: ", data['message'])
        return None
    else:
        abi = data['result']
        return abi

def abi_modifier(contract_address, option='add', chain_id=1):
    if os.path.isfile('abis.json'):
        with open('abis.json') as json_file:
            abis = json.load(json_file)
    else:
        abis = {}

    if option == 'add':
        if contract_address not in abis:
            abi = fetch_abi(contract_address, chain_id)
            abis[contract_address] = abi
        with open('abis.json', 'w') as outfile:
            json.dump(abis, outfile)

    elif option == 'remove':
        if contract_address in abis:
            del abis[contract_address]
        with open('abis.json', 'w') as outfile:
            json.dump(abis, outfile)

def get_abi(contract_address, chain_id=1):
    if os.path.isfile('abis.json'):
        with open('abis.json') as json_file:
            abis = json.load(json_file)
            if contract_address in abis:
                return abis[contract_address]
            else:
                abi_modifier(contract_address, 'add', chain_id)
                return get_abi(contract_address, chain_id)
    else:
        abi_modifier(contract_address, 'add', chain_id)
        return get_abi(contract_address, chain_id)

class Token:
    def __init__(self, address, chain_id='1') -> None:
        self.chain_id = chain_id
        self.address = address
        self.pair_address = UNISWAP_V2_FACTORY_CONTRACT.functions.getPair(self.address, WETH).call()
        self.contract = w3.eth.contract(address=address, abi=get_abi(address))
        self.pair_contract = w3.eth.contract(address=self.pair_address, abi=fetch_abi(self.pair_address, self.chain_id))
    def get_info(self):
        name, symbol, total_supply, owner = None, None, None, None
        try:
            name = self.contract.functions.name().call()
            symbol = self.contract.functions.symbol().call()
            total_supply = self.contract.functions.totalSupply().call()
            owner = self.contract.functions.owner().call()
        except Exception:
            pass
        return name, symbol, total_supply, owner
    def get_reserves(self):
        reserves = self.pair_contract.functions.getReserves().call()
        return reserves
    def get_price_weth(self):
        reserve = self.get_reserves()
        token_decimals = self.contract.functions.decimals().call()
        WETH_decimals = 18
        if self.address < WETH:
            token_0_reserve = reserve[0]/10**token_decimals
            token_1_reserve = reserve[1]/10**WETH_decimals
        else:
            token_0_reserve = reserve[1]/10**token_decimals
            token_1_reserve = reserve[0]/10**WETH_decimals
        return token_1_reserve/token_0_reserve
    def approve_to_router(self):
        max_uint96 = (2 ** 96) - 1
        max_uint256 = (2 ** 256) - 1
        allowance = self.contract.functions.allowance(ACCOUNT.address, UNISWAP_V2_ROUTER).call()
        if allowance == max_uint96 ^ allowance == max_uint256:
            approve_tx = self.contract.functions.approve(UNISWAP_V2_ROUTER, max_uint256).build_transaction({
                "from": ACCOUNT.address,
                "nonce": w3.eth.get_transaction_count(ACCOUNT.address),
                "gas": 60000,
                "maxFeePerGas": 2000000000, 
                "maxPriorityFeePerGas": 1500000000,
            })
            signed_approve_tx = w3.eth.account.sign_transaction(approve_tx, private_key=ACCOUNT._private_key.hex())
            tx_hash = w3.eth.send_raw_transaction(signed_approve_tx.rawTransaction)
            tx = w3.eth.wait_for_transaction_receipt(tx_hash)
            if tx.status == 1:
                print("Token approved")
                return tx
            else:
                print("Token approval failed")
                return tx
        else:
            print("Token already approved")
            return None
    def buy(self, amount_in, slippage):
        amountOutMin = amount_in * (1 - slippage)
        buy_tx = UNISWAP_V2_ROUTER_CONTRACT.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            w3.to_wei(amountOutMin, 'ether'),       # amountOutMin
            [WETH, self.address],                   # path (path 0 needs to be WETH)
            ACCOUNT.address,                        # to
            int(datetime.now().timestamp()) + 60    # deadline (current + 60s)
        ).build_transaction({
            "from": ACCOUNT.address,
            "nonce": w3.eth.get_transaction_count(ACCOUNT.address),
            "value": w3.to_wei(amount_in, 'ether'),
            "gas": 300000,
            "maxFeePerGas": 2000000000,
            "maxPriorityFeePerGas": 1500000000,
        })
        signed_buy_tx = w3.eth.account.sign_transaction(buy_tx, private_key=ACCOUNT._private_key.hex())
        tx_hash = w3.eth.send_raw_transaction(signed_buy_tx.rawTransaction)
        tx = w3.eth.wait_for_transaction_receipt(tx_hash)
        if tx.status == 1:
            print("Buy successful")
            self.approve_to_router()
            return tx
        else:
            print("Buy failed")
            return tx

def main():
    print("Welcome to Unitrade bot by @edmundtcy, the current version is 0.1.0")
    keys = key_initizer()
    RPC = {
        'mainnet': f'https://mainnet.infura.io/v3/{keys["infura_key"]}',
        'goreli': f'https://goerli.infura.io/v3/{keys["infura_key"]}',
        'mainnet_mev': f'https://rpc.mevblocker.io',
        'mainnet_ws': f'wss://mainnet.infura.io/ws/v3/{keys["infura_key"]}',
        'goreli_ws': f'wss://goerli.infura.io/ws/v3/{keys["infura_key"]}',
    }
    
    global w3
    global ACCOUNT
    global ETHERSCAN_KEY
    global UNISWAP_V2_ROUTER
    global UNISWAP_V2_FACTORY
    global UNISWAP_V2_ROUTER_CONTRACT
    global UNISWAP_V2_FACTORY_CONTRACT
    global WETH

    ETHERSCAN_KEY = keys["etherscan_key"]
    ACCOUNT = Account.from_key(keys["private_key"])
    network = input("Please enter the network you want to connect to mainnet/goreli (m/g): ")
    if network == 'm':
        w3 = Web3(Web3.HTTPProvider(RPC['mainnet_mev'], request_kwargs={'timeout': 60}))
        infura_w3 = Web3(Web3.HTTPProvider(RPC['mainnet'], request_kwargs={'timeout': 60}))
    elif network == 'g':
        w3 = Web3(Web3.HTTPProvider(RPC['goreli'], request_kwargs={'timeout': 60}))

    UNISWAP_V2_FACTORY = Web3.to_checksum_address("0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f")
    UNISWAP_V2_ROUTER = Web3.to_checksum_address("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")
    abi_modifier(UNISWAP_V2_FACTORY, 'add', 1)
    abi_modifier(UNISWAP_V2_ROUTER, 'add', 1)
    UNISWAP_V2_FACTORY_CONTRACT = w3.eth.contract(address=UNISWAP_V2_FACTORY, abi=get_abi(UNISWAP_V2_FACTORY))
    UNISWAP_V2_ROUTER_CONTRACT = w3.eth.contract(address=UNISWAP_V2_ROUTER, abi=get_abi(UNISWAP_V2_ROUTER))
    WETH = UNISWAP_V2_ROUTER_CONTRACT.functions.WETH().call()

    print(f'Time: {datetime.now()}')
    print(f'Chain ID: {w3.eth.chain_id}')
    print(f'Current block number: {w3.eth.block_number}')
    print(f'Infura block number: {infura_w3.eth.block_number}')
    print(f'Account address: {ACCOUNT.address}')
    print(f'Account balance: {w3.from_wei(w3.eth.get_balance(ACCOUNT.address), "ether")} ETH')
    print("Enter the the token address you want to Buy/Sell: ")

    while True:
        #Detect token address
        #0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984
        token_address = input("Token address: ")
        if w3.is_address(token_address):
            token_address = Web3.to_checksum_address(token_address)
            code = w3.eth.get_code(token_address)
            if code == b'':
                print(f"The address {token_address} is not a contract or does not exit.")
            else:
                token = Token(token_address, w3.eth.chain_id)

                name, symbol, total_supply, owner = token.get_info()
                print(f"Token name: {name}")
                print(f"Token symbol: {symbol}")
                print(f"Token total supply: {total_supply}")
                print(f"Token owner: {owner}")
                print(f'{symbol}/WETH price: {token.get_price_weth()}')

main()