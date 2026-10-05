"""Bounded BOLT11 field inspection. Paying wallet verifies the invoice signature."""
import re

CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'


def decode_invoice(invoice):
    if not isinstance(invoice, str) or not 120 <= len(invoice) <= 8192 or (invoice != invoice.lower() and invoice != invoice.upper()):
        raise ValueError('Invalid invoice encoding')
    invoice = invoice.lower()
    split = invoice.rfind('1')
    hrp = invoice[:split]
    match = re.fullmatch(r'lnbc([1-9][0-9]*)([munp]?)', hrp)
    if not match:
        raise ValueError('Require amount-bound Bitcoin mainnet invoice')
    try:
        data = [CHARSET.index(c) for c in invoice[split+1:]]
    except ValueError:
        raise ValueError('Invalid invoice encoding') from None
    check = 1
    for value in [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + data:
        top, check = check >> 25, ((check & 0x1ffffff) << 5) ^ value
        for bit, generator in enumerate((0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3)):
            if (top >> bit) & 1:
                check ^= generator
    if check != 1 or len(data) < 7 + 104 + 6:
        raise ValueError('Invalid invoice checksum or length')
    def number(values):
        result = 0
        for value in values: result = result * 32 + value
        return result
    def hash_bytes(values):
        if len(values) != 52 or values[-1] & 15:
            raise ValueError('Invalid invoice hash')
        return (number(values) >> 4).to_bytes(32, 'big').hex()
    amount = int(match[1]) * {'':100_000_000_000,'m':100_000_000,'u':100_000,'n':100,'p':1}[match[2]]
    if match[2] == 'p':
        if amount % 10: raise ValueError('Fractional millisatoshi invoice')
        amount //= 10
    timestamp, tags, pos, end = number(data[:7]), {}, 7, len(data)-110
    while pos < end:
        if pos + 3 > end: raise ValueError('Truncated invoice tag')
        tag, length = CHARSET[data[pos]], number(data[pos+1:pos+3])
        pos += 3
        if pos + length > end: raise ValueError('Truncated invoice field')
        if tag in {'p','h','x'}:
            if tag in tags: raise ValueError('Duplicate invoice field')
            tags[tag] = data[pos:pos+length]
        pos += length
    if not {'p', 'h'} <= tags.keys():
        raise ValueError('Invoice requires payment and description hashes')
    return {'amount_msat':amount,'payment_hash':hash_bytes(tags['p']),
            'description_hash':hash_bytes(tags['h']),
            'expires':timestamp + (number(tags['x']) if 'x' in tags else 3600)}
