"""B站 BV号 与 AV号 互转"""

TABLE = "fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF"
S = [11, 10, 3, 8, 4, 6]
XOR = 177451812
ADD = 8728348608


def bv2av(bv: str) -> int:
    """BV号转AV号"""
    r = 0
    for i in range(6):
        r += TABLE.index(bv[S[i]]) * (58**i)
    return (r - ADD) ^ XOR


def av2bv(av: int) -> str:
    """AV号转BV号"""
    av = (av ^ XOR) + ADD
    r = list("BV1  4 1 7  ")
    for i in range(6):
        r[S[i]] = TABLE[av // (58**i) % 58]
    return "".join(r)
