// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

import {Test, console} from "forge-std/Test.sol";
import "@openzeppelin/contracts/utils/math/SafeMath.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import {UQ112x112} from "../src/libraries/UQ112x112.sol";

import "../src/interfaces/IUniswapV2Router02.sol";
import "../src/interfaces/IUniswapV2Factory.sol";
import "../src/interfaces/IUniswapV2Pair.sol";

import {HelperContract} from "./HelperContract.sol";
import {BootstrapBot} from "../src/BootstrapBot.sol";
import {ERC20Token} from "../src/ERC20Token.sol";

contract BootstrapBotTest is Test, HelperContract {
  using SafeMath for uint256;
  using UQ112x112 for uint224;

  BootstrapBot public bot;

  function setUp() public {
    token = new ERC20Token();
    bot = new BootstrapBot(ROUTERV2, FACTORYV2, WETH);
  }

  function test_addLiquidity() public {
    token.transfer(address(bot), TOTAL_SUPPLY);
    bot.approveToken(ROUTERV2, address(token), TOTAL_SUPPLY);
    bot.addLiquidity{value: INITIAL_AVAX_RESERVE}(address(token), TOTAL_SUPPLY);

    (uint256 reserve0, uint256 reserve1, ) = IUniswapV2Pair(_getPair()).getReserves();

    assertGt(reserve0, 0);
    assertGt(reserve1, 0);
  }

}