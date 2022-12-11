def c_to_f(value):
        return value * 1.8 + 32

if __name__ == '__main__':
    value = input('Temperature in C: ')
    print(c_to_f(value))