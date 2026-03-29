'''
დაწერერეთ პროგრამა რომელის მეშვეობითაც მომხმარებელი შეძლებს შეამოწმოს, 
ხელმისაწვდომია თუ არა მატარებელში, კონკრეტულ ვაგონში კონკრეტული, ადგილი. 
მომხმარებელს უნდა შეეძლოს შეიტანოს ვაგონისა და ადგილის ნომერი. იმ შემთხვევაში, 
თუ არჩეული ადგილი დაკავებულია, შესთავაზეთ უახლოესი ადგილი და თუ ვაგონში არ არის თავისუფალი ადგილები,
 პროგრამამ გააგრძელოს ძიება სხვა ვაგონებში სანამ არ იპოვის თავისუფალ ადგილს. გამოიყენეთ ქვემოთ მოცემული დიქშენერი.

p.s
ვაგონის ნომერია key ხოლო ამავე ვაგონის data არის value
'''

data = {
    1: [
        { "seat_name": "a1", "isTaken": True },
        { "seat_name": "a2", "isTaken": True },
        { "seat_name": "a3", "isTaken": True },
        { "seat_name": "a4", "isTaken": True },
        { "seat_name": "a5", "isTaken": True },
    ],
    2: [
        { "seat_name": "b1", "isTaken": False },
        { "seat_name": "b2", "isTaken": False },
        { "seat_name": "b3", "isTaken": True },
        { "seat_name": "b4", "isTaken": False },
        { "seat_name": "b5", "isTaken": True },
    ],
    3: [
        { "seat_name": "c1", "isTaken": False },
        { "seat_name": "c2", "isTaken": True },
        { "seat_name": "c3", "isTaken": True },
        { "seat_name": "c4", "isTaken": True },
        { "seat_name": "c5", "isTaken": False },
    ],
}


def find_seat_index(seats, seat_name):
    for i, seat in enumerate(seats):
        if seat["seat_name"] == seat_name:
            return i
    return None


def find_closest_seat(seats, index):
    distance = 1

    while distance < len(seats):

        # check right
        if index + distance < len(seats):
            if not seats[index + distance]["isTaken"]:
                return seats[index + distance]["seat_name"]

        # check left
        if index - distance >= 0:
            if not seats[index - distance]["isTaken"]:
                return seats[index - distance]["seat_name"]

        distance += 1

    return None


def find_seat_other_wagons(data, current_wagon):
    for wagon, seats in data.items():
        if wagon == current_wagon:
            continue

        for seat in seats:
            if not seat["isTaken"]:
                return wagon, seat["seat_name"]

    return None


def main():

    wagon = int(input("Enter wagon number: "))
    seat_name = input("Enter seat name: ")

    if wagon not in data:
        print("Wagon does not exist")
    else:

        seats = data[wagon]
        index = find_seat_index(seats, seat_name)

        if index is None:
            print("Seat not found")

        elif not seats[index]["isTaken"]:
            print("Seat is free")

        else:
            print("Seat is taken")

            closest = find_closest_seat(seats, index)

            if closest:
                print("Nearest free seat:", closest)

            else:
                result = find_seat_other_wagons(data, wagon)

                if result:
                    w, s = result
                    print("Free seat in wagon", w, "seat", s)
                else:
                    print("No seats available")



if __name__ == "__main__":
    main()