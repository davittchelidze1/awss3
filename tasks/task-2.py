# დაწერეთ CLI პროგრამა Argparse ის გამოყენებთ რომელიც პარამეტრად მიიღებს
# მაგალითად: 'testStringBTu1.23123asd43plm4234'
# აქედან უნდა შეძლოთ 1.23123 ამოღება და floatList ში გადაწერა
# 43 ის oddList ში ხოლო 4234 მნიშვნელობის გადატანა evenList ში
# საბოლოოდ დაბეჭდეთ მიღებული მნიშვნელობები.


import argparse
import re


def extract_numbers(input_string: str) -> tuple[list[float], list[int], list[int]]:
    float_list = []
    odd_list = []
    even_list = []

    float_numbers = re.findall(r'\d+\.\d+', input_string)

    for num in float_numbers:
        float_list.append(float(num))
        input_string = input_string.replace(num, " ")

    int_numbers = re.findall(r'\d+', input_string)

    for num in int_numbers:
        value = int(num)
        if value % 2 == 0:
            even_list.append(value)
        else:
            odd_list.append(value)

    return float_list, odd_list, even_list


def main():
    parser = argparse.ArgumentParser(
        description="CLI პროგრამა რომელიც ამოღებს float, odd და even რიცხვებს სტრინგიდან."
    )
    parser.add_argument("input_string", help="input string")
    args = parser.parse_args()

    float_list, odd_list, even_list = extract_numbers(args.input_string)

    print("Float რიცხვები:", float_list)
    print("კენტი რიცხვები:", odd_list)
    print("ლუწი რიცხვები:", even_list)


if __name__ == "__main__":
    main()