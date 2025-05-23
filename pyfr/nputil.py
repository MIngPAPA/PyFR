import ctypes as ct
import functools as ft
import itertools as it
import re

import numpy as np


def block_diag(arrs):
    shapes = [a.shape for a in arrs]
    out = np.zeros(np.sum(shapes, axis=0), dtype=arrs[0].dtype)

    r, c = 0, 0
    for i, (rr, cc) in enumerate(shapes):
        out[r:r + rr, c:c + cc] = arrs[i]
        r += rr
        c += cc

    return out


def clean(origfn=None, tol=1e-10, ckwarg='clean'):
    def cleanfn(fn):
        @ft.wraps(fn)
        def newfn(*args, **kwargs):
            if not kwargs.pop(ckwarg, True):
                return fn(*args, **kwargs)

            arr = fn(*args, **kwargs).copy()

            # Flush small elements to zero
            arr[np.abs(arr) < tol] = 0

            # Coalesce similar elements
            if arr.size > 1:
                amfl = np.abs(arr.flat)
                amix = np.argsort(amfl)

                i, ix = 0, amix[0]
                for j, jx in enumerate(amix[1:], start=1):
                    if not np.isclose(amfl[jx], amfl[ix], rtol=tol,
                                      atol=0.1*tol):
                        if j - i > 1:
                            amfl[amix[i:j]] = np.median(amfl[amix[i:j]])
                        i, ix = j, jx

                if i != j:
                    amfl[amix[i:]] = np.median(amfl[amix[i:]])

                # Fix up the signs and assign
                arr.flat = np.copysign(amfl, arr.flat)

            return arr
        return newfn

    return cleanfn(origfn) if origfn else cleanfn


def morton_encode(ipts, imax, dtype=np.uint64):
    # Allocate the codes
    codes = np.zeros(len(ipts), dtype=dtype)

    # Determine how many bits to use for each input dimension
    ndims = ipts.shape[1]
    obits = 8*codes.dtype.itemsize
    ibits = dtype(obits // ndims)
    ishift = np.array([max(int(p).bit_length() - ibits, 0) for p in imax])

    # Compute the masks and shifts
    ops = [[(1 << j, (ndims - 1)*j + i) for j in range(ibits)]
           for i in range(ndims)]

    # Cache-block the arrays
    n = max(1, len(codes) // 16384)
    bipts = np.array_split(ipts, n)
    bcodes = np.array_split(codes, n)

    # Loop over each block
    for ipt, code in zip(bipts, bcodes):
        # Loop over each dimension
        for p, pops in zip((ipt >> ishift).T, ops):
            # Extract and interleave the bits
            for mask, shift in pops:
                code |= (p & mask) << shift

    return codes


_npeval_syms = {
    '__builtins__': {},
    'exp': np.exp, 'log': np.log,
    'sin': np.sin, 'asin': np.arcsin,
    'cos': np.cos, 'acos': np.arccos,
    'tan': np.tan, 'atan': np.arctan, 'atan2': np.arctan2,
    'abs': np.abs, 'pow': np.power, 'sqrt': np.sqrt,
    'tanh': np.tanh, 'pi': np.pi,
    'max': np.maximum, 'min': np.minimum
}


def npeval(expr, locals):
    # Disallow direct exponentiation
    if '^' in expr or '**' in expr:
        raise ValueError('Direct exponentiation is not supported; use pow')

    # Ensure the expression does not contain invalid characters
    if not re.match(r'[A-Za-z0-9_ \t\n\r.,+\-*/%()]+$', expr):
        raise ValueError('Invalid characters in expression')

    # Disallow access to object attributes
    objs = '|'.join(it.chain(_npeval_syms, locals))
    if re.search(rf'({objs}|\))\s*\.', expr):
        raise ValueError('Invalid expression')

    return eval(expr, _npeval_syms, locals)


def fuzzysort(arr, idx, dim=0, tol=1e-6):
    # Extract our dimension and argsort
    arrd = arr[dim]
    srtdidx = sorted(idx, key=arrd.__getitem__)

    if len(srtdidx) > 1:
        i, ix = 0, srtdidx[0]
        for j, jx in enumerate(srtdidx[1:], start=1):
            if arrd[jx] - arrd[ix] >= tol:
                if j - i > 1:
                    srtdidx[i:j] = fuzzysort(arr, srtdidx[i:j], dim + 1, tol)
                i, ix = j, jx

        if i != j:
            srtdidx[i:] = fuzzysort(arr, srtdidx[i:], dim + 1, tol)

    return srtdidx


def iter_struct(arr, n=1000, axis=0):
    for c in np.array_split(arr, -(arr.shape[axis] // -n) or 1, axis=axis):
        yield from c.tolist()


_ctype_map = {
    np.int32: 'int', np.uint32: 'unsigned int',
    np.int64: 'int64_t', np.uint64: 'uint64_t',
    np.float32: 'float', np.float64: 'double'
}


def npdtype_to_ctype(dtype):
    return _ctype_map[np.dtype(dtype).type]


_ctypestype_map = {
    np.int32: ct.c_int32, np.uint32: ct.c_uint32,
    np.int64: ct.c_int64, np.uint64: ct.c_uint64,
    np.float32: ct.c_float, np.float64: ct.c_double
}


def npdtype_to_ctypestype(dtype):
    # Special-case None which otherwise expands to np.float
    if dtype is None:
        return None

    return _ctypestype_map[np.dtype(dtype).type]
