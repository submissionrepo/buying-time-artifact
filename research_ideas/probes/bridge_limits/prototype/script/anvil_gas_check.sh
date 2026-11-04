#!/usr/bin/env bash
# Cross-check of the GasBench numbers: replays the same steady state on a local anvil node
# (Prague rules) and prints gasUsed from the transaction receipts. Each measurement starts
# from an anvil snapshot of the steady state.  Usage: bash script/anvil_gas_check.sh
set -euo pipefail
export PATH="$HOME/.foundry/bin:$PATH"
cd "$(dirname "$0")/.."

PORT=8555
RPC=http://127.0.0.1:$PORT
GENESIS=1760000000
T0=$((GENESIS + 100))                  # leaves room for the deployment blocks
H=3600
DAY=86400
ZERO=0x0000000000000000000000000000000000000000
B=1000000000000000000000000            # 1,000,000 USD, 18 decimals
R=11574074074074074074                 # B per day
WAD=1000000000000000000
K1=1000000000000000000000              # 1,000 USD
K450=450000000000000000000000          # 450,000 USD
BIG=1000000000000000000000000000       # 1e27

anvil --port $PORT --hardfork prague --timestamp $GENESIS --silent &
ANVIL=$!
trap 'kill $ANVIL' EXIT
for _ in $(seq 60); do # wait until the node answers
    cast chain-id --rpc-url $RPC > /dev/null 2>&1 && break
    sleep 0.5
done

read -r DEPLOYER BRIDGE ADMIN PAUSER RCPT HOLDER < <(cast rpc --rpc-url $RPC eth_accounts |
    python -c "import json,sys; print(' '.join(json.load(sys.stdin)[:6]))" | tr -d '\r')

deploy() { # contract, constructor args...
    local c=$1; shift
    local args=()
    if [ $# -gt 0 ]; then args=(--constructor-args "$@"); fi
    forge create "$c" --rpc-url $RPC --unlocked --from $DEPLOYER --broadcast --json "${args[@]}" |
        python -c "import json,sys; print(json.load(sys.stdin)['deployedTo'])"
}
send() { # from, to, signature, args... -> prints gasUsed
    local out
    out=$(cast send --rpc-url $RPC --unlocked --from "$@" --json)
    echo "$out" | python -c "import json,sys; r=json.load(sys.stdin); assert r.get('status')=='0x1', r; print(int(r['gasUsed'],16))"
}
at() { cast rpc --rpc-url $RPC evm_setNextBlockTimestamp "$1" > /dev/null; }

LIM=$(deploy src/OutflowLimiter.sol:OutflowLimiter $BRIDGE $ADMIN $PAUSER $ZERO $B $R $H)
PLAIN=$(deploy src/Baselines.sol:PlainEscrow $BRIDGE)
WINDOW=$(deploy src/Baselines.sol:SlidingWindowCap $BRIDGE $ADMIN $B)
USD=$(deploy test/mocks/Tokens.sol:TestToken)
WRAPPED=$(deploy test/mocks/Tokens.sol:WrappedToken $LIM)

send $ADMIN $LIM "listAsset(address,uint256,bool)" $USD $WAD false > /dev/null
send $ADMIN $LIM "listAsset(address,uint256,bool)" $WRAPPED $WAD true > /dev/null
send $ADMIN $WINDOW "listAsset(address,uint256)" $USD $WAD > /dev/null
for a in $LIM $PLAIN $WINDOW $HOLDER; do send $DEPLOYER $USD "faucet(address,uint256)" $a $BIG > /dev/null; done
send $DEPLOYER $USD "faucet(address,uint256)" $RCPT $WAD > /dev/null

Q="requestRelease(address,address,uint256)"
REL="release(address,address,uint256)"
at $T0
send $BRIDGE $LIM $Q $USD $RCPT $K450 > /dev/null
send $BRIDGE $LIM $Q $USD $RCPT $K450 > /dev/null
send $BRIDGE $LIM $Q $WRAPPED $RCPT $K1 > /dev/null
send $BRIDGE $WINDOW $REL $USD $RCPT $K1 > /dev/null
at $((T0 + H))
for i in 1 2 3; do send $DEPLOYER $LIM "executeNext()" > /dev/null; done
send $BRIDGE $LIM $Q $USD $RCPT $K1 > /dev/null       # id 3
send $BRIDGE $LIM $Q $WRAPPED $RCPT $K1 > /dev/null   # id 4
send $BRIDGE $LIM $Q $USD $RCPT $K1 > /dev/null       # id 5
send $BRIDGE $WINDOW $REL $USD $RCPT $K1 > /dev/null
at $((T0 + 2 * H))
send $BRIDGE $WINDOW $REL $USD $RCPT $K1 > /dev/null
SNAP=$(cast rpc --rpc-url $RPC evm_snapshot | tr -d '"')

fresh() { # restore the steady state and set the time of the next block
    cast rpc --rpc-url $RPC evm_revert "$SNAP" > /dev/null
    SNAP=$(cast rpc --rpc-url $RPC evm_snapshot | tr -d '"')
    at "$1"
}

T=$((T0 + 2 * H + 60))
fresh $T; echo "token_transfer $(send $HOLDER $USD 'transfer(address,uint256)' $RCPT $K1)"
fresh $T; echo "plain_release $(send $BRIDGE $PLAIN $REL $USD $RCPT $K1)"
fresh $T; echo "window_release $(send $BRIDGE $WINDOW $REL $USD $RCPT $K1)"
fresh $((T0 + DAY + 60)); echo "window_release_expire1 $(send $BRIDGE $WINDOW $REL $USD $RCPT $K1)"
fresh $((T0 + DAY + 2 * H + 60)); echo "window_release_expire3 $(send $BRIDGE $WINDOW $REL $USD $RCPT $K1)"
fresh $T; echo "limiter_queue $(send $BRIDGE $LIM $Q $USD $RCPT $K1)"
fresh $T; echo "limiter_execute_escrow $(send $DEPLOYER $LIM 'executeNext()')"
fresh $T; send $DEPLOYER $LIM 'executeNext()' > /dev/null
at $((T + 60)); echo "limiter_execute_mint $(send $DEPLOYER $LIM 'executeNext()')"
fresh $T; send $PAUSER $LIM 'cancel(uint256)' 4 > /dev/null; send $DEPLOYER $LIM 'executeNext()' > /dev/null
at $((T + 60)); echo "limiter_execute_escrow_skip1 $(send $DEPLOYER $LIM 'executeNext()')"
fresh $T; echo "limiter_cancel $(send $PAUSER $LIM 'cancel(uint256)' 5)"
fresh $T; echo "limiter_pause $(send $PAUSER $LIM 'pause()')"
