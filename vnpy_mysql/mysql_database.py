from datetime import datetime

from peewee import (
    AutoField,
    CharField,
    DateTimeField,
    DoubleField,
    IntegerField,
    Model,
    MySQLDatabase as PeeweeMySQLDatabase,
    ModelSelect,
    ModelDelete,
    chunked,
    fn,
    Asc,
    Desc
)
from playhouse.shortcuts import ReconnectMixin

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, TickData
from vnpy.trader.database import (
    BaseDatabase,
    BarOverview,
    TickOverview,
    DB_TZ,
    convert_tz
)
from vnpy.trader.setting import SETTINGS


class ReconnectMySQLDatabase(ReconnectMixin, PeeweeMySQLDatabase):
    """带有重连混入的MySQL数据库类"""
    pass

db = ReconnectMySQLDatabase(
    database=SETTINGS["database.database"],
    user=SETTINGS["database.user"],
    password=SETTINGS["database.password"],
    host=SETTINGS["database.host"],
    port=SETTINGS["database.port"]
)


class DateTimeMillisecondField(DateTimeField):
    """支持毫秒的日期时间戳字段"""

    def get_modifiers(self) -> list:
        """毫秒支持"""
        return [3]


class DbBarData(Model):
    """K线数据表映射对象"""

    id: AutoField = AutoField()

    symbol: CharField = CharField()
    exchange: CharField = CharField()
    datetime: DateTimeField = DateTimeField()
    interval: CharField = CharField()

    volume: DoubleField = DoubleField()
    turnover: DoubleField = DoubleField()
    open_interest: DoubleField = DoubleField()
    open_price: DoubleField = DoubleField()
    high_price: DoubleField = DoubleField()
    low_price: DoubleField = DoubleField()
    close_price: DoubleField = DoubleField()

    class Meta:
        database: PeeweeMySQLDatabase = db
        indexes: tuple = ((("symbol", "exchange", "interval", "datetime"), True),)


class DbTickData(Model):
    """TICK数据表映射对象"""

    id: AutoField = AutoField()

    symbol: CharField = CharField()
    exchange: CharField = CharField()
    datetime: DateTimeField = DateTimeMillisecondField()

    name: CharField = CharField()
    volume: DoubleField = DoubleField()
    turnover: DoubleField = DoubleField()
    open_interest: DoubleField = DoubleField()
    last_price: DoubleField = DoubleField()
    last_volume: DoubleField = DoubleField()
    limit_up: DoubleField = DoubleField()
    limit_down: DoubleField = DoubleField()

    open_price: DoubleField = DoubleField()
    high_price: DoubleField = DoubleField()
    low_price: DoubleField = DoubleField()
    pre_close: DoubleField = DoubleField()

    bid_price_1: DoubleField = DoubleField()
    bid_price_2: DoubleField = DoubleField(null=True)
    bid_price_3: DoubleField = DoubleField(null=True)
    bid_price_4: DoubleField = DoubleField(null=True)
    bid_price_5: DoubleField = DoubleField(null=True)

    ask_price_1: DoubleField = DoubleField()
    ask_price_2: DoubleField = DoubleField(null=True)
    ask_price_3: DoubleField = DoubleField(null=True)
    ask_price_4: DoubleField = DoubleField(null=True)
    ask_price_5: DoubleField = DoubleField(null=True)

    bid_volume_1: DoubleField = DoubleField()
    bid_volume_2: DoubleField = DoubleField(null=True)
    bid_volume_3: DoubleField = DoubleField(null=True)
    bid_volume_4: DoubleField = DoubleField(null=True)
    bid_volume_5: DoubleField = DoubleField(null=True)

    ask_volume_1: DoubleField = DoubleField()
    ask_volume_2: DoubleField = DoubleField(null=True)
    ask_volume_3: DoubleField = DoubleField(null=True)
    ask_volume_4: DoubleField = DoubleField(null=True)
    ask_volume_5: DoubleField = DoubleField(null=True)

    localtime: DateTimeField = DateTimeMillisecondField(null=True)

    class Meta:
        database: PeeweeMySQLDatabase = db
        indexes: tuple = ((("symbol", "exchange", "datetime"), True),)


class DbBarOverview(Model):
    """K线汇总数据表映射对象"""

    id: AutoField = AutoField()

    symbol: CharField = CharField()
    exchange: CharField = CharField()
    interval: CharField = CharField()
    count: IntegerField = IntegerField()
    start: DateTimeField = DateTimeField()
    end: DateTimeField = DateTimeField()

    class Meta:
        database: PeeweeMySQLDatabase = db
        indexes: tuple = ((("symbol", "exchange", "interval"), True),)


class DbTickOverview(Model):
    """Tick汇总数据表映射对象"""

    id: AutoField = AutoField()

    symbol: CharField = CharField()
    exchange: CharField = CharField()
    count: IntegerField = IntegerField()
    start: DateTimeField = DateTimeField()
    end: DateTimeField = DateTimeField()

    class Meta:
        database: PeeweeMySQLDatabase = db
        indexes: tuple = ((("symbol", "exchange"), True),)


class MysqlDatabase(BaseDatabase):
    """Mysql数据库接口"""

    def __init__(self) -> None:
        """"""
        self.db: PeeweeMySQLDatabase = db
        self.db.connect()

        # 如果数据表不存在，则执行创建初始化
        if not DbBarData.table_exists():
            self.db.create_tables([DbBarData, DbTickData, DbBarOverview, DbTickOverview])

    def save_bar_data(self, bars: list[BarData], stream: bool = False) -> bool:
        """保存K线数据"""
        # 读取主键参数
        bar: BarData = bars[0]
        symbol: str = bar.symbol
        exchange: Exchange = bar.exchange
        interval: Interval = bar.interval

        # 将BarData数据转换为字典，并调整时区
        data: list = []

        for bar in bars:
            bar.datetime = convert_tz(bar.datetime)

            d: dict = bar.__dict__
            d["exchange"] = d["exchange"].value
            d["interval"] = d["interval"].value
            d.pop("gateway_name")
            d.pop("vt_symbol")
            d.pop("extra", None)
            data.append(d)

        # 使用upsert操作将数据更新到数据库中
        with self.db.atomic():
            for c in chunked(data, 50):
                DbBarData.insert_many(c).on_conflict_replace().execute()

        # 更新K线汇总数据
        overview: DbBarOverview = DbBarOverview.get_or_none(
            DbBarOverview.symbol == symbol,
            DbBarOverview.exchange == exchange.value,
            DbBarOverview.interval == interval.value,
        )

        if not overview:
            overview = DbBarOverview()
            overview.symbol = symbol
            overview.exchange = exchange.value
            overview.interval = interval.value
            overview.start = bars[0].datetime
            overview.end = bars[-1].datetime
            overview.count = len(bars)
        elif stream:
            overview.end = bars[-1].datetime
            overview.count += len(bars)
        else:
            overview.start = min(bars[0].datetime, overview.start)
            overview.end = max(bars[-1].datetime, overview.end)

            s: ModelSelect = DbBarData.select().where(
                (DbBarData.symbol == symbol)
                & (DbBarData.exchange == exchange.value)
                & (DbBarData.interval == interval.value)
            )
            overview.count = s.count()

        overview.save()

        return True

    def save_tick_data(self, ticks: list[TickData], stream: bool = False) -> bool:
        """保存TICK数据"""
        # 读取主键参数
        tick: TickData = ticks[0]
        symbol: str = tick.symbol
        exchange: Exchange = tick.exchange

        # 将TickData数据转换为字典，并调整时区
        data: list = []

        for tick in ticks:
            tick.datetime = convert_tz(tick.datetime)

            d: dict = tick.__dict__
            d["exchange"] = d["exchange"].value
            d.pop("gateway_name")
            d.pop("vt_symbol")
            d.pop("extra", None)
            data.append(d)

        # 使用upsert操作将数据更新到数据库中
        with self.db.atomic():
            for c in chunked(data, 50):
                DbTickData.insert_many(c).on_conflict_replace().execute()

        # 更新Tick汇总数据
        overview: DbTickOverview = DbTickOverview.get_or_none(
            DbTickOverview.symbol == symbol,
            DbTickOverview.exchange == exchange.value,
        )

        if not overview:
            overview = DbTickOverview()
            overview.symbol = symbol
            overview.exchange = exchange.value
            overview.start = ticks[0].datetime
            overview.end = ticks[-1].datetime
            overview.count = len(ticks)
        elif stream:
            overview.end = ticks[-1].datetime
            overview.count += len(ticks)
        else:
            overview.start = min(ticks[0].datetime, overview.start)
            overview.end = max(ticks[-1].datetime, overview.end)

            s: ModelSelect = DbTickData.select().where(
                (DbTickData.symbol == symbol)
                & (DbTickData.exchange == exchange.value)
            )
            overview.count = s.count()

        overview.save()

        return True

    def load_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> list[BarData]:
        """"""
        s: ModelSelect = (
            DbBarData.select().where(
                (DbBarData.symbol == symbol)
                & (DbBarData.exchange == exchange.value)
                & (DbBarData.interval == interval.value)
                & (DbBarData.datetime >= start)
                & (DbBarData.datetime <= end)
            ).order_by(DbBarData.datetime)
        )

        bars: list[BarData] = []
        for db_bar in s:
            bar: BarData = BarData(
                symbol=db_bar.symbol,
                exchange=Exchange(db_bar.exchange),
                datetime=datetime.fromtimestamp(db_bar.datetime.timestamp(), DB_TZ),
                interval=Interval(db_bar.interval),
                volume=db_bar.volume,
                turnover=db_bar.turnover,
                open_interest=db_bar.open_interest,
                open_price=db_bar.open_price,
                high_price=db_bar.high_price,
                low_price=db_bar.low_price,
                close_price=db_bar.close_price,
                gateway_name="DB"
            )
            bars.append(bar)

        return bars

    def load_tick_data(
        self,
        symbol: str,
        exchange: Exchange,
        start: datetime,
        end: datetime
    ) -> list[TickData]:
        """读取TICK数据"""
        s: ModelSelect = (
            DbTickData.select().where(
                (DbTickData.symbol == symbol)
                & (DbTickData.exchange == exchange.value)
                & (DbTickData.datetime >= start)
                & (DbTickData.datetime <= end)
            ).order_by(DbTickData.datetime)
        )

        ticks: list[TickData] = []
        for db_tick in s:
            tick: TickData = TickData(
                symbol=db_tick.symbol,
                exchange=Exchange(db_tick.exchange),
                datetime=datetime.fromtimestamp(db_tick.datetime.timestamp(), DB_TZ),
                name=db_tick.name,
                volume=db_tick.volume,
                turnover=db_tick.turnover,
                open_interest=db_tick.open_interest,
                last_price=db_tick.last_price,
                last_volume=db_tick.last_volume,
                limit_up=db_tick.limit_up,
                limit_down=db_tick.limit_down,
                open_price=db_tick.open_price,
                high_price=db_tick.high_price,
                low_price=db_tick.low_price,
                pre_close=db_tick.pre_close,
                bid_price_1=db_tick.bid_price_1,
                bid_price_2=db_tick.bid_price_2,
                bid_price_3=db_tick.bid_price_3,
                bid_price_4=db_tick.bid_price_4,
                bid_price_5=db_tick.bid_price_5,
                ask_price_1=db_tick.ask_price_1,
                ask_price_2=db_tick.ask_price_2,
                ask_price_3=db_tick.ask_price_3,
                ask_price_4=db_tick.ask_price_4,
                ask_price_5=db_tick.ask_price_5,
                bid_volume_1=db_tick.bid_volume_1,
                bid_volume_2=db_tick.bid_volume_2,
                bid_volume_3=db_tick.bid_volume_3,
                bid_volume_4=db_tick.bid_volume_4,
                bid_volume_5=db_tick.bid_volume_5,
                ask_volume_1=db_tick.ask_volume_1,
                ask_volume_2=db_tick.ask_volume_2,
                ask_volume_3=db_tick.ask_volume_3,
                ask_volume_4=db_tick.ask_volume_4,
                ask_volume_5=db_tick.ask_volume_5,
                localtime=db_tick.localtime,
                gateway_name="DB"
            )
            ticks.append(tick)

        return ticks

    def delete_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval
    ) -> int:
        """删除K线数据"""
        d: ModelDelete = DbBarData.delete().where(
            (DbBarData.symbol == symbol)
            & (DbBarData.exchange == exchange.value)
            & (DbBarData.interval == interval.value)
        )
        count: int = d.execute()

        # 删除K线汇总数据
        d2: ModelDelete = DbBarOverview.delete().where(
            (DbBarOverview.symbol == symbol)
            & (DbBarOverview.exchange == exchange.value)
            & (DbBarOverview.interval == interval.value)
        )
        d2.execute()
        return count

    def delete_tick_data(
        self,
        symbol: str,
        exchange: Exchange
    ) -> int:
        """删除TICK数据"""
        d: ModelDelete = DbTickData.delete().where(
            (DbTickData.symbol == symbol)
            & (DbTickData.exchange == exchange.value)
        )

        count: int = d.execute()

        # 删除Tick汇总数据
        d2: ModelDelete = DbTickOverview.delete().where(
            (DbTickOverview.symbol == symbol)
            & (DbTickOverview.exchange == exchange.value)
        )
        d2.execute()
        return count

    def get_bar_overview(self) -> list[BarOverview]:
        """查询数据库中的K线汇总信息"""
        # 如果已有K线，但缺失汇总信息，则执行初始化
        data_count: int = DbBarData.select().count()
        overview_count: int = DbBarOverview.select().count()
        if data_count and not overview_count:
            self.init_bar_overview()

        s: ModelSelect = DbBarOverview.select()
        overviews: list[BarOverview] = []
        for overview in s:
            overview.exchange = Exchange(overview.exchange)
            overview.interval = Interval(overview.interval)
            overviews.append(overview)
        return overviews

    def get_tick_overview(self) -> list[TickOverview]:
        """查询数据库中的Tick汇总信息"""
        s: ModelSelect = DbTickOverview.select()
        overviews: list = []
        for overview in s:
            overview.exchange = Exchange(overview.exchange)
            overviews.append(overview)
        return overviews

    def init_bar_overview(self) -> None:
        """初始化数据库中的K线汇总信息"""
        s: ModelSelect = (
            DbBarData.select(
                DbBarData.symbol,
                DbBarData.exchange,
                DbBarData.interval,
                fn.COUNT(DbBarData.id).alias("count")
            ).group_by(
                DbBarData.symbol,
                DbBarData.exchange,
                DbBarData.interval
            )
        )

        for data in s:
            overview: DbBarOverview = DbBarOverview()
            overview.symbol = data.symbol
            overview.exchange = data.exchange
            overview.interval = data.interval
            overview.count = data.count

            start_bar: DbBarData = (
                DbBarData.select()
                .where(
                    (DbBarData.symbol == data.symbol)
                    & (DbBarData.exchange == data.exchange)
                    & (DbBarData.interval == data.interval)
                )
                .order_by(Asc(DbBarData.datetime))
                .first()
            )
            overview.start = start_bar.datetime

            end_bar: DbBarData = (
                DbBarData.select()
                .where(
                    (DbBarData.symbol == data.symbol)
                    & (DbBarData.exchange == data.exchange)
                    & (DbBarData.interval == data.interval)
                )
                .order_by(Desc(DbBarData.datetime))
                .first()
            )
            overview.end = end_bar.datetime

            overview.save()
