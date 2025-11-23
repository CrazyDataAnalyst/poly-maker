const { BigNumber, ethers } = require('ethers');


/**
 * Joins an array of hexadecimal strings into a single hexadecimal string.
 *
 * @param {string[]} hexData - An array of hexadecimal strings.
 * @returns {string} The combined hexadecimal string.
 */
function joinHexData(hexData) {
    return `0x${hexData
        .map(hex => {
            const stripped = hex.replace(/^0x/, "");
            return stripped.length % 2 === 0 ? stripped : "0" + stripped;
        })
        .join("")}`;
}


/**
 * ABI-encodes and packs a list of parameters.
 *
 * @param {...{type: string, value: any}} params - The parameters to encode.
 * @returns {string} The ABI-encoded and packed hexadecimal string.
 */
function abiEncodePacked(...params) {
    return joinHexData(
        params.map(({ type, value }) => {
            const encoded = ethers.utils.defaultAbiCoder.encode([type], [value]);

            if (type === "bytes" || type === "string") {
                const bytesLength = parseInt(encoded.slice(66, 130), 16);
                return encoded.slice(130, 130 + 2 * bytesLength);
            }

            let typeMatch = type.match(/^(?:u?int\d*|bytes\d+|address)\[\]$/);
            if (typeMatch) {
                return encoded.slice(130);
            }

            if (type.startsWith("bytes")) {
                const bytesLength = parseInt(type.slice(5));
                return encoded.slice(2, 2 + 2 * bytesLength);
            }

            typeMatch = type.match(/^u?int(\d*)$/);
            if (typeMatch) {
                if (typeMatch[1] !== "") {
                    const bytesLength = parseInt(typeMatch[1]) / 8;
                    return encoded.slice(-2 * bytesLength);
                }
                return encoded.slice(-64);
            }

            if (type === "address") {
                return encoded.slice(-40);
            }

            throw new Error(`unsupported type ${type}`);
        })
    );
}


/**
 * Signs a transaction hash with a given signer.
 *
 * @param {ethers.Signer} signer - The signer to use for signing.
 * @param {string} message - The message (transaction hash) to sign.
 * @returns {Promise<{r: string, s: string, v: string}>} A promise that resolves with the r, s, and v components of the signature.
 */
async function signTransactionHash(signer, message) {
    const messageArray = ethers.utils.arrayify(message);
    let sig = await signer.signMessage(messageArray);
    let sigV = parseInt(sig.slice(-2), 16);

    switch (sigV) {
        case 0:
        case 1:
            sigV += 31;
            break;
        case 27:
        case 28:
            sigV += 4;
            break;
        default:
            throw new Error("Invalid signature");
    }

    sig = sig.slice(0, -2) + sigV.toString(16);

    return {
        r: BigNumber.from("0x" + sig.slice(2, 66)).toString(),
        s: BigNumber.from("0x" + sig.slice(66, 130)).toString(),
        v: BigNumber.from("0x" + sig.slice(130, 132)).toString(),
    };
}


/**
 * Signs and executes a transaction through a Gnosis Safe.
 *
 * @param {ethers.Signer} signer - The signer to use for the transaction.
 * @param {ethers.Contract} safe - The Gnosis Safe contract instance.
 * @param {string} to - The destination address for the transaction.
 * @param {string} data - The data payload for the transaction.
 * @param {object} [overrides={}] - Ethers transaction overrides.
 * @returns {Promise<ethers.providers.TransactionResponse>} A promise that resolves with the transaction response.
 */
async function signAndExecuteSafeTransaction(signer, safe, to, data, overrides = {}) {
    const nonce = await safe.nonce();
    console.log("Nonce for safe: ", nonce);
    const value = "0";
    const safeTxGas = "0";
    const baseGas = "0";
    const gasPrice = "0";
    const gasToken = ethers.constants.AddressZero;
    const refundReceiver = ethers.constants.AddressZero;
    const operation = 0;

    const txHash = await safe.getTransactionHash(
        to,
        value,
        data,
        operation,
        safeTxGas,
        baseGas,
        gasPrice,
        gasToken,
        refundReceiver,
        nonce
    );
    console.log("Transaction hash: ", txHash);

    const rsvSignature = await signTransactionHash(signer, txHash);
    const packedSig = abiEncodePacked(
        { type: "uint256", value: rsvSignature.r },
        { type: "uint256", value: rsvSignature.s },
        { type: "uint8", value: rsvSignature.v }
    );

    console.log("Executing transaction");

    return safe.execTransaction(
        to,
        value,
        data,
        operation,
        safeTxGas,
        baseGas,
        gasPrice,
        gasToken,
        refundReceiver,
        packedSig,
        overrides
    );
}

module.exports = {
    signAndExecuteSafeTransaction,
};