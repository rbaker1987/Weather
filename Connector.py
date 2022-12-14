from sqlalchemy import create_engine, ForeignKey, Column, Integer, String, DateTime, Text, Float, dialects, MetaData, \
    insert, select
from sqlalchemy.orm import declarative_base, sessionmaker
from NWS import NWS

engine = create_engine(f'postgresql+psycopg2://postgres:Map2022$@localhost/Weather')

connection = engine.connect()

Base = declarative_base()


class Observations(Base):
    __tablename__ = 'observations'

    elevation = Column(Float())
    station = Column(String())
    temperature = Column(Float())
    dewpoint = Column(Float())
    windDirection = Column(String())
    windSpeed = Column(Float())
    windGust = Column(Float())
    barometricPressure = Column(Float())
    seaLevelPressure = Column(Float())
    visibility = Column(Float())
    maxTemperatureLast24Hours = Column(Float())
    minTemperatureLast24Hours = Column(Float())
    precipitationLastHour = Column(Float())
    precipitationLast3Hours = Column(Float())
    precipitationLast6Hours = Column(Float())
    relativeHumidity = Column(Float())
    windChill = Column(Float())
    heatIndex = Column(Float())
    valid = Column(String(), primary_key=True)


class Forecasts(Base):
    __tablename__ = 'forecasts'

    heatIndex = Column(Float())
    windChill = Column(Float())
    skyCover = Column(Float())
    windDirection = Column(String())
    windSpeed = Column(Float())
    windGust = Column(Float())
    weather = Column(String())
    probabilityOfPrecipitation = Column(Float())
    quantitativePrecipitation = Column(Float())
    iceAccumulation = Column(Float())
    snowfallAmount = Column(Float())
    transportWindSpeed = Column(Float())
    transportWindDirection = Column(String())
    mixingHeight = Column(Float())
    twentyFootWindSpeed = Column(Float())
    twentyFootWindDirection = Column(String())
    valid = Column(String(), primary_key=True)


Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)
session = Session()
nws = NWS(75771)
o = nws.observations()
f = nws.forecasts()
with engine.connect() as conn:
    result = conn.execute(select(Forecasts))
f_keys = result.keys()
for i, row in enumerate(f):
    for k in f_keys:
        if k not in row:
            f[i][k] = 0
session.execute(insert(Observations), o)
# session.execute(insert(Forecasts), f)
session.commit()
print()
