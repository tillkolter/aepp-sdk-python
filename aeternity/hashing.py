import base58
import rlp
import uuid
import secrets
from nacl.hash import blake2b
from nacl.encoding import RawEncoder
from nacl import secret, utils
from nacl.pwhash import argon2id

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


def _base58_decode(encoded_str):
    """decode a base58 string to bytes"""
    return base58.b58decode_check(encoded_str)


def _base58_encode(data):
    """create a base58 encoded string"""
    return base58.b58encode_check(data)


def _blacke2b_digest(data):
    """create a blacke2b 32 bit raw encoded digest"""
    return blake2b(data=data, digest_size=32, encoder=RawEncoder)


def _sha256(data):
    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(data)
    return digest.finalize()


def encode(prefix, data):
    """encode data using the default encoding/decoding algorithm and prepending the prefix with a prefix, ex: ak_encoded_data, th_encoded_data,..."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return f"{prefix}_{base58.b58encode_check(data)}"


def decode(data):
    """
    Decode data using the default encoding/decoding algorithm
    :param data: a encoded and prefixed string (ex tx_..., sg_..., ak_....)
    :return: the raw byte array of the decoded hashed
    """

    if data is None or len(data.strip()) < 3 or data[2] != '_':
        raise ValueError('Invalid hash')
    return _base58_decode(data[3:])


def encode_rlp(prefix, data):
    """
    Encode an array in rlp format
    :param prefix: the prefix to use in the encoded string
    :param data: the array that has to be encoded in rlp
    """
    if not isinstance(data, list):
        raise ValueError("data to be encoded to rlp must be an array")
    payload = rlp.encode(data)
    return encode(prefix, payload)


def hash(data):
    """run the default hashing algorithm"""
    return _blacke2b_digest(data)


def hash_encode(prefix, data):
    """run the default hashing + digest algorithms"""
    return encode(prefix, hash(data))


def namehash(name):
    if isinstance(name, str):
        name = name.encode('ascii')
    # see:
    # https://github.com/aeternity/protocol/blob/master/AENS.md#hashing
    # and also:
    # https://github.com/ethereum/EIPs/blob/master/EIPS/eip-137.md#namehash-algorithm
    labels = name.split(b'.')
    hashed = b'\x00' * 32
    while labels:
        hashed = hash(hashed + hash(labels[0]))
        labels = labels[1:]
    return hashed


def namehash_encode(prefix, name):
    return encode(prefix, namehash(name))


def randint(upper_bound=2**64):
    return secrets.randbelow(upper_bound)


def randbytes(size=32):
    return secrets.token_bytes(size)


def keystore_seal(private_key, password, address, name=""):
    # password
    salt = utils.random(argon2id.SALTBYTES)
    mem = argon2id.MEMLIMIT_MODERATE
    ops = argon2id.OPSLIMIT_MODERATE
    key = argon2id.kdf(secret.SecretBox.KEY_SIZE, password.encode(), salt, opslimit=ops, memlimit=mem)
    # ciphertext
    box = secret.SecretBox(key)
    nonce = utils.random(secret.SecretBox.NONCE_SIZE)
    sk = private_key.encode(encoder=RawEncoder) + private_key.verify_key.encode(encoder=RawEncoder)
    ciphertext = box.encrypt(sk, nonce=nonce).ciphertext
    # build the keystore
    k = {
        "public_key": address,
        "crypto": {
            "secret_type": "ed25519",
            "symmetric_alg": "xsalsa20-poly1305",
            "ciphertext": bytes.hex(ciphertext),
            "cipher_params": {
                "nonce": bytes.hex(nonce)
            },
            "kdf": "argon2id",
            "kdf_params": {
                "memlimit_kib": round(mem / 1024),
                "opslimit": ops,
                "salt": bytes.hex(salt),
                "parallelism": 1  # pynacl 1.3.0 doesnt support this parameter
            }
        },
        "id": str(uuid.uuid4()),
        "name": name,
        "version": 1
    }
    return k


def keystore_open(k, password):
    # password
    salt = bytes.fromhex(k.get("crypto", {}).get("kdf_params", {}).get("salt"))
    ops = k.get("crypto", {}).get("kdf_params", {}).get("opslimit")
    mem = k.get("crypto", {}).get("kdf_params", {}).get("memlimit_kib") * 1024
    par = k.get("crypto", {}).get("kdf_params", {}).get("parallelism")
    # pynacl 1.3.0 doesnt support this parameter and can only use 1
    if par != 1:
        raise ValueError(f"Invalid parallelism {par} value, only parallelism = 1 is supported in the python sdk")
    key = argon2id.kdf(secret.SecretBox.KEY_SIZE, password.encode(), salt, opslimit=ops, memlimit=mem)
    # decrypt
    box = secret.SecretBox(key)
    nonce = bytes.fromhex(k.get("crypto", {}).get("cipher_params", {}).get("nonce"))
    encrypted = bytes.fromhex(k.get("crypto", {}).get("ciphertext"))
    private_key = box.decrypt(encrypted, nonce=nonce, encoder=RawEncoder)
    return private_key
