class MetricToImperial:
    def c_to_f(self, value):
        return value * 1.8 + 32

if __name__ == '__main__':
    mi = MetricToImperial()
    value = input('Temperature in C: ')
    mi.c_to_f(value)