## Bot smart contracts
This folder contains source code of Sniper bot.

### Build

```shell
$ forge build
```

### Fork test

```shell
$ forge test --fork-url <rpc-url> -vvvv
```

### Format

```shell
$ forge fmt
```

### Gas Snapshots

```shell
$ forge snapshot
```

### Anvil

```shell
$ anvil
```

### Deploy

- Deploy Factory
```shell
$ forge create \
--rpc-url <rpc-url> \
--private-key <private-key> \
src/Factory.sol:Factory
```

- Deploy Bot implementation
```shell
$ forge create \
--rpc-url <rpc-url> \
--private-key <private-key> \
src/SnipeBot.sol:SnipeBot
```

### Cast

```shell
$ cast <subcommand>
```

### Help

```shell
$ forge --help
$ anvil --help
$ cast --help
```

### Cleanup

```shell
$ forge clean
```