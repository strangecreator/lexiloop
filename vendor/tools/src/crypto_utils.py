import random


__all__ = [
    "generate_password",
]


limits = {
    'letters': ((ord('A'), ord('Z')), (ord('a'), ord('z'))),
    'letters_with_numbers': ((ord('0'), ord('9')), (ord('A'), ord('Z')), (ord('a'), ord('z')))
}


def randint_by_intervals(*args: tuple):
    length = sum(map(lambda x: x[1] - x[0] + 1, args))
    number = random.randint(1, length)

    for i, j in args:
        if j - i + 1 < number:
            number -= (j - i + 1)
        else:
            return i + number - 1


def generate_password(length: int=8):
    result = chr(randint_by_intervals(*limits['letters']))

    for _ in range(length - 1):
        result += chr(randint_by_intervals(*limits['letters_with_numbers']))

    return result