// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IWeightSource} from "../../src/OutflowLimiter.sol";

/// Minimal ERC20 used by the tests and the gas runs.
abstract contract ERC20Base {
    uint8 public constant decimals = 18;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _move(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 a = allowance[from][msg.sender];
        if (a != type(uint256).max) allowance[from][msg.sender] = a - amount;
        _move(from, to, amount);
        return true;
    }

    function _move(address from, address to, uint256 amount) internal {
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }

    function _mint(address to, uint256 amount) internal {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function _burn(address from, uint256 amount) internal {
        balanceOf[from] -= amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }
}

/// Escrowed asset; anyone may mint for test setup.
contract TestToken is ERC20Base {
    function faucet(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/// Wrapped asset on the destination chain; only the minter (the limiter) mints and burns.
contract WrappedToken is ERC20Base {
    address public immutable minter;

    constructor(address minter_) {
        minter = minter_;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == minter, "not minter");
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external {
        require(msg.sender == minter, "not minter");
        _burn(from, amount);
    }
}

/// Settable weight source for the optional adapter test.
contract MockWeightSource is IWeightSource {
    mapping(address => uint256) public weightOf;

    function set(address asset, uint256 w) external {
        weightOf[asset] = w;
    }
}
