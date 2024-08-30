// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

import "@openzeppelin/contracts/access/Ownable.sol";

contract Factory is Ownable {  
  event BotCreated(address indexed owner, address bot);

  function createBot(address implementation,
    bytes32 salt,
    address owner,
    address router,
    address factory,
    address weth) external onlyOwner returns (address) {
    assembly {
      //pop(owner)
      pop(router)
      pop(factory)
      pop(weth)

      calldatacopy(0x8c, 0x44, 0x80) // copy (owner, router, factory, weth) total 4 bytes to memory, starts at 0x8c

      mstore(0x6c, 0x5af43d82803e903d91602b57fd5bf3) // ERC-1167 footer, 15B length, laid out at 0x7d -> 0x8c
      mstore(0x5d, implementation) // implementation address, 20B length, laid out at 0x69 -> 0x7d
      mstore(0x49, 0x3d60cd80600a3d3981f3363d3d373d3d3d363d73) // ERC-1167 constructor + header, 20B length, laid out at 0x55 -> 0x69

      // Copy create2 computation data to memory
      mstore8(0x00, 0xff) // 0xFF
      mstore(0x35, keccak256(0x55, 0xb7)) // keccak256(bytecode), which starts at 0x55 and has length 0xb7
      mstore(0x01, shl(96, address())) // factory address
      mstore(0x15, salt) // salt

      // Compute account address
      let computed := keccak256(0x00, 0x55)

      // If the account has not yet been deployed
      if iszero(extcodesize(computed)) {
          // Deploy account contract
          let deployed := create2(0, 0x55, 0xb7, salt)

          // Revert if the deployment fails
          if iszero(deployed) {
            revert(0x1c, 0x04)
          }

          // Store account address in memory before salt and chainId
          mstore(0x6c, deployed)

          // emit event
          log2(0x6c, 0x20, 0x7432e04fa82e37552c086d411ea5879c9f6024585cb7f7facbac1f64788dac23, owner)

          // Return the account address
          return(0x6c, 0x20)
      }

      // Otherwise, return the computed account address
      mstore(0x00, shr(96, shl(96, computed)))
      return(0x00, 0x20)
    }
  }

}