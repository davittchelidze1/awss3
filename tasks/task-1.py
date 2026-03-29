# დაწერეთ კოდი რომელიც აარჩევს და ამოწერს 9 დან 9999 მდე შუალედში მყოფ ყველა არმსტრონგის რიცხვს. რის
# შემდეგაც დაწერეთ ეს რიცხვები და მათი ჯამი, თუმცა ჯამისთვის გამოიყენეთ თქვენი დაწერილი რეკურსიული ფუნქცია.

# არმსტრონგის რიცხვებია:
# *9 არის არმსტრონგის რიცხვი რადგან 9 = 9^1
# *10 არ არის არმსტრონგის რიცხვი რადგან 10 != 1^2 + 0^2
# *153 არის არმსტრონგის რიცხვი რადგან 153 = 1^3+ 5^3 + 3^3 = 1 + 125 + 27 = 153

# თქვენი დავალებაა გადააკეთოთ ეს პირობა CLI სკრიპტად Argparse ის გამოყენებით, ასევე დაიცავით Python ის მართლწერის სტილი.



import argparse


def is_armstrong(number: int) -> bool:
    digits = str(number)
    power = len(digits)

    total = sum(int(digit) ** power for digit in digits)

    return total == number


def recursive_sum(numbers: list[int]) -> int:
    if not numbers:
        return 0
    return numbers[0] + recursive_sum(numbers[1:])


def find_armstrong(start: int, end: int) -> list[int]:
    result = []

    for num in range(start, end + 1):
        if is_armstrong(num):
            result.append(num)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="ვიპოვოთ არმსტრონგის რიცხვები და მათი ჯამი შუალედში 9 დან 9999 მდე."
    )

    parser.add_argument(
        "--start",
        type=int,
        default=9,
        help="რეინჯის დასაწყისი (default: 9)"
    )

    parser.add_argument(
        "--end",
        type=int,
        default=9999,
        help="რეინჯის დასასრული (default: 9999)"
    )

    args = parser.parse_args()

    armstrong_numbers = find_armstrong(args.start, args.end)

    total_sum = recursive_sum(armstrong_numbers)

    print("არმსტრონგის რიცხვები:")
    for number in armstrong_numbers:
        print(number)

    print("\nარმსტრონგის რიცხვების ჯამი:", total_sum)


if __name__ == "__main__":
    main()