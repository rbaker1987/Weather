from datetime import datetime


def round_temp(temp: int):
    temp = str(temp)
    if int(temp[-1]) in [0, 1, 2]:
        return f'around {temp[:-1]}0'
    elif int(temp[-1]) in [8, 9]:
        return f'around {str(int(temp[:-1])+1)}0'
    elif int(temp[-1]) in [3, 4, 5, 6, 7]:
        return f'the mid {temp[:-1]}0s'


def trend_temp(am_t: int, pm_t: int):
    if abs(am_t - pm_t) in [0, 1, 2]:
        return 'steady'
    elif am_t < pm_t:
        return 'rising'
    elif am_t > pm_t:
        return 'falling'


def parse_temperature(am_t: int, pm_t: int):
    am_t_str = round_temp(am_t)
    pm_t_str = round_temp(pm_t)
    trend_str = trend_temp(am_t, pm_t)
    if trend_str == 'steady':
        if am_t < pm_t:
            temp_str = f'holding steady {round_temp(pm_t)}'
        else:
            temp_str = f'holding steady {round_temp(am_t)}'
    else:
        if 'the' in am_t_str:
            temp_str = f'starting in {am_t_str} and {trend_str} to {pm_t_str}'
        else:
            temp_str = f'starting {am_t_str} and {trend_str} to {pm_t_str}'
    return temp_str


def parse_weather(weather):
    split = weather.split(' ')
    if len(split) == 1:
        return weather.lower().capitalize()
    else:
        word_list = []
        for word in split:
            if word == 'AM':
                word_list.append('morning')
            elif word == 'PM':
                word_list.append('afternoon')
            else:
                word_list.append(word.lower())

        string = ' '.join(word_list)
        return string.capitalize()


def create_text_output(data):
    output = []
    for i, row in enumerate(data):
        date = datetime.strptime(row[0], "%Y-%m-%d").strftime("%m/%d")
        am_temp = int(row[2])
        pm_temp = int(row[3])
        weather = row[4]
        if i == 0:
            day = 'Today'
        elif i == 1:
            day = 'Tomorrow'
        else:
            day = row[1]

        output.append(
            f"{date} {day} \n{parse_weather(weather)} with temperatures {parse_temperature(am_temp, pm_temp)}.")
    return '\n'.join(output)


if __name__ == '__main__':
    data = [('2022-12-18', 'Sunday', '24', '46', 'Sunny'), ('2022-12-19', 'Monday', '38', '40', 'Rainy'),
            ('2022-12-20', 'Tuesday', '33', '46', 'AM Rain Showers and PM Clouds'),
            ('2022-12-21', 'Wednesday', '28', '44', 'SOme Clouds'),
            ('2022-12-22', 'Thursday', '42', '24', 'AM Rain Showers and PM Snow Showers'),
            ('2022-12-23', 'Friday', '6', '24', 'Some Clouds')]
    o = create_text_output(data)
    print(o)
    print()
