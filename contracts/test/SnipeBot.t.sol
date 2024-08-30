// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

import "forge-std/Test.sol";
import "@openzeppelin/contracts/utils/math/SafeMath.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "../src/libraries/UQ112x112.sol";

import "../src/interfaces/IUniswapV2Router02.sol";
import "../src/interfaces/IUniswapV2Factory.sol";
import "../src/interfaces/IUniswapV2Pair.sol";

import {Factory} from "../src/Factory.sol";
import {HelperContract} from "./HelperContract.sol";
import {SnipeBot} from "../src/SnipeBot.sol";
import {BootstrapBot} from "../src/BootstrapBot.sol";
import {ERC20Token} from "../src/ERC20Token.sol";

contract SnipeBotTest is Test, HelperContract {
  uint256 private constant INSPECT_VALUE = 10**15;

  event Swap(
    address indexed sender,
    uint256 amount0In,
    uint256 amount1In,
    uint256 amount0Out,
    uint256 amount1Out,
    address indexed to
  );

  event Transfer(address indexed from, address indexed to, uint256 amount);

  using SafeMath for uint256;
  using UQ112x112 for uint224;

  Factory public factory;
  SnipeBot public snipeBotImpl;
  SnipeBot public snipeBot;
  BootstrapBot public bootstrapBot;

  fallback() external payable {}

  receive() external payable {}

  function setUp() public {
    token = new ERC20Token();
    bootstrapBot = new BootstrapBot(ROUTERV2, FACTORYV2, WETH);

    //snipeBot = new SnipeBot(ROUTERV2, FACTORYV2, WETH); // deprecated

    factory = new Factory();
    snipeBotImpl = new SnipeBot();
    address deployed = factory.createBot(address(snipeBotImpl), keccak256(abi.encode(block.timestamp)), address(this), ROUTERV2, FACTORYV2, WETH);
    snipeBot = SnipeBot(payable(deployed));

    token.transfer(address(bootstrapBot), TOTAL_SUPPLY/2);
    bootstrapBot.approveToken(ROUTERV2, address(token), TOTAL_SUPPLY/2);
    bootstrapBot.addLiquidity{value: INITIAL_AVAX_RESERVE}(address(token), TOTAL_SUPPLY/2);
  }

  function test_BuyRevertedDueUnauthorized() public{
    vm.expectRevert();
    vm.prank(address(1));

    snipeBot.buy{value: INSPECT_VALUE}(address(token), block.timestamp + DEADLINE_BLOCK_DELAY);
  }

  function test_BuySuccess() public {
    uint[] memory amounts = snipeBot.buy{value: INSPECT_VALUE}(address(token), block.timestamp + DEADLINE_BLOCK_DELAY);

    assertEq(amounts[0], INSPECT_VALUE);
    assertGt(amounts[1], 0);
  }

  function test_SellRevertedDueUnauthorized() public {
    vm.expectRevert();
    vm.prank(address(1));
    snipeBot.sell(address(token), address(this), block.timestamp + DEADLINE_BLOCK_DELAY);
  }

  function test_SellSuccess() public {
    uint[] memory amountBuy = snipeBot.buy{value: INSPECT_VALUE}(address(token), block.timestamp + DEADLINE_BLOCK_DELAY);
    uint[] memory amountSell = snipeBot.sell(address(token), address(this), block.timestamp + DEADLINE_BLOCK_DELAY);

    assertEq(amountBuy[1], amountSell[0]);
    assertGt(amountSell[1], INSPECT_VALUE*9/10);
  }

  function test_InspectTransferRevertedDueUnauthorized() public {
    vm.expectRevert();
    vm.prank(address(1));
    snipeBot.inspect_transfer(address(token), TOTAL_SUPPLY/4);
  }

  function test_InspectTransferSuccess() public {
    token.approve(address(snipeBot), TOTAL_SUPPLY/4);
    uint256 received = snipeBot.inspect_transfer(address(token), TOTAL_SUPPLY/4);
    assertEq(received, TOTAL_SUPPLY/4);
  }

}