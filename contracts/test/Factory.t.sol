// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.13;

import "forge-std/Test.sol";
import "@openzeppelin/contracts/utils/math/SafeMath.sol";
import {UQ112x112} from "../src/libraries/UQ112x112.sol";

import {Factory} from "../src/Factory.sol";
import {SnipeBot} from "../src/SnipeBot.sol";

import {HelperContract} from "./HelperContract.sol";

contract FactoryTest is Test, HelperContract {
  Factory public factory;
  SnipeBot public snipeBot;

  error InitializedAlready();
  event BotCreated(address indexed owner, address bot);

  fallback() external payable {}

  event Receive(uint256 amount);
  receive() external payable {
    emit Receive(msg.value);
  }

  function setUp() public {
    // factory
    factory = new Factory();

    // implementation
    snipeBot = new SnipeBot();
  }

  function test_createBotRevertedDueUnauthorized() public {
    vm.expectRevert();
    vm.prank(address(1));

    factory.createBot(address(snipeBot), keccak256(abi.encode(block.timestamp)), address(1), ROUTERV2, FACTORYV2, WETH);
  }

  function test_createBotSuccess() public {
    vm.expectEmit(true, false, false, false);
    emit BotCreated(address(this), address(0));

    address deployed = factory.createBot(address(snipeBot), keccak256(abi.encode(block.timestamp)), address(this), ROUTERV2, FACTORYV2, WETH);
    assertNotEq(deployed, address(0));

    (address owner, address router, address factoryV2, address weth)  = SnipeBot(payable(deployed)).config();
    assertEq(owner, address(this));
    assertEq(router, ROUTERV2);
    assertEq(factoryV2, FACTORYV2);
    assertEq(weth, WETH);
  }

}