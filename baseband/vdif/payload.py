"""
Definitions for VLBI VDIF payloads.

Implements a VDIFPayload class used to store payload words, and decode to
or encode from a data array.

For the VDIF specification, see http://www.vlbi.org/vdif
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import numpy as np

from ..vlbi_base.payload import VLBIPayloadBase
from ..vlbi_base.encoding import (encode_2bit_base, encode_4bit_base,
                                  decoder_levels, decode_8bit, encode_8bit)

__all__ = ['init_luts', 'decode_2bit', 'encode_2bit',
           'VDIFPayload']


def init_luts():
    """Set up the look-up tables for levels as a function of input byte.

    S10. in http://vlbi.org/vdif/docs/VDIF_specification_Release_1.1.1.pdf
    states that samples are encoded by offset-binary, such that all 0 bits is
    lowest and all 1 bits is highest.  I.e., for 2-bit sampling, the order is
    00, 01, 10, 11.
    """
    b = np.arange(256)[:, np.newaxis]
    # 1-bit mode
    i = np.arange(8)
    lut1bit = decoder_levels[1][(b >> i) & 1]
    # 2-bit mode
    i = np.arange(0, 8, 2)
    lut2bit = decoder_levels[2][(b >> i) & 3]
    # 4-bit mode
    i = np.arange(0, 8, 4)
    lut4bit = decoder_levels[4][(b >> i) & 0xf]
    return lut1bit, lut2bit, lut4bit

lut1bit, lut2bit, lut4bit = init_luts()


def decode_2bit(words):
    b = words.view(np.uint8)
    return lut2bit.take(b, axis=0)


shift2bit = np.arange(0, 8, 2).astype(np.uint8)


def encode_2bit(values):
    bitvalues = encode_2bit_base(values.reshape(-1, 4))
    bitvalues <<= shift2bit
    return np.bitwise_or.reduce(bitvalues, axis=-1)


def decode_4bit(words):
    b = words.view(np.uint8)
    return lut4bit.take(b, axis=0)


shift04 = np.array([0, 4], np.uint8)


def encode_4bit(values):
    b = encode_4bit_base(values).reshape(-1, 2)
    b <<= shift04
    return b[:, 0] | b[:, 1]


class VDIFPayload(VLBIPayloadBase):
    """Container for decoding and encoding VDIF payloads.

    Parameters
    ----------
    words : ndarray
        Array containg LSB unsigned words (with the right size) that
        encode the payload.
    header : `~baseband.vdif.VDIFHeader`, optional
        Information needed to interpret payload.  If not given, the
        following keywords need to be set.

    --- If no `header is given :

    nchan : int, optional
        Number of channels.  Default: 1.
    bps : int, optional
        Bits per sample (or real, imaginary component).  Default: 2.
    complex_data : bool
        Complex or float data.  Default: `False`.
    """
    _decoders = {2: decode_2bit,
                 4: decode_4bit,
                 8: decode_8bit}

    _encoders = {2: encode_2bit,
                 4: encode_4bit,
                 8: encode_8bit}

    def __init__(self, words, header=None,
                 nchan=1, bps=2, complex_data=False):
        if header is not None:
            nchan = header.nchan
            bps = header.bps
            complex_data = header['complex_data']
            self._size = header.payloadsize
            if header.edv == 0xab:  # Mark5B payload
                from ..mark5b import Mark5BPayload
                self._decoders = Mark5BPayload._decoders
                self._encoders = Mark5BPayload._encoders
                if complex_data:
                    raise ValueError("VDIF/Mark5B payload cannot be complex.")
        super(VDIFPayload, self).__init__(words, bps=bps,
                                          sample_shape=(nchan,),
                                          complex_data=complex_data)
        self.nchan = nchan

    @classmethod
    def fromfile(cls, fh, header):
        """Read payload from file handle and decode it into data.

        Parameters
        ----------
        fh : filehandle
            To read data from.
        header : `~baseband.vdif.VDIFHeader`
            Used to infer the payloadsize, number of channels, bits per sample,
            and whether the data is complex.
        """
        s = fh.read(header.payloadsize)
        if len(s) < header.payloadsize:
            raise EOFError("Could not read full payload.")
        return cls(np.fromstring(s, dtype=cls._dtype_word), header)

    @classmethod
    def fromdata(cls, data, header=None, bps=2, edv=None):
        """Encode data as payload, using header information.

        Parameters
        ----------
        data : ndarray
            Values to be encoded.
        header : `~baseband.vdif.VDIFHeader`, optional
            If given, used to infer the encoding, and to verify the number of
            channels and whether the data is complex.
        bps : int, optional
            Used if header is not given.
        edv : int, optional
            Should be given if not header is specified and the payload is
            encoded as Mark 5 data (i.e., edv=0xab).
        """
        nchan = data.shape[-1]
        complex_data = (data.dtype.kind == 'c')
        if header is not None:
            if header.nchan != nchan:
                raise ValueError("Header is for {0} channels but data has {1}"
                                 .format(header.nchan, data.shape[-1]))
            if header['complex_data'] != complex_data:
                raise ValueError("Header is for {0} data but data is {1}"
                                 .format(*(('complex' if c else 'real') for c
                                           in (header['complex_data'],
                                               complex_data))))
            bps = header.bps
            edv = header.edv

        if edv == 0xab:  # Mark5B payload
            from ..mark5b import Mark5BPayload
            encoder = Mark5BPayload._encoders[bps]
        else:
            encoder = cls._encoders[bps]

        if complex_data:
            data = data.view((data.real.dtype, (2,)))
        words = encoder(data).ravel().view(cls._dtype_word)
        return cls(words, header, nchan=nchan, bps=bps,
                   complex_data=complex_data)
