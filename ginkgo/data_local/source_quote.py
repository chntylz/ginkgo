# -*- coding:utf-8 -*-
"""
@author: ksf

@since: 2019-11-07 10:14
"""
import os
import numpy as np
from collections import defaultdict

from ginkgo.core.model import Frame, SFrame
from ginkgo.data_local.source_date_index import RowDateIndex
from ginkgo.data_local.source_symbol_index import ColSymbolIndex
from ginkgo.data_local.ingester import StandardQuoteIngester
from ginkgo.data_local.interface import LocalDataBase
from ginkgo.data_local.fields import fields_manager, fields_dict
from ginkgo.utils.logger import logger


class QuoteModel(LocalDataBase):

    def __init__(self, base_path, fields_dict=fields_dict,
                 chunks_s_num=300, catgory='stock', freq='daily', market='CN'):

        self._base_path = os.path.join(base_path, f'{catgory.lower()}/{market.lower()}/{freq.lower()}')
        self._market = market
        self._fields_dict = fields_dict
        self._date_index = RowDateIndex(self._base_path, catgory=catgory, market=market)
        self._chunks_s_num = chunks_s_num
        self._symbol_index = ColSymbolIndex(self._base_path, chunks_s_num=chunks_s_num, catgory=catgory, market=market)
        self._fields_dir_path = \
            {field: os.path.join(self._base_path, f'{field.name}') for field in self._fields_dict.values()}
        self._check_dir(self._fields_dir_path.values())
        self._memmap_files_dict = defaultdict(dict)

        # method proxy
        self.get_calendar = self._date_index.get_calendar
        self.contracts_filter = self._symbol_index.contracts_filter
        self.get_date_offset = self._date_index.offset

    def _check_dir(self, dirs):
        for d in dirs:
            self.check_file(d, is_dir=True)

    def ingest(self, codes, start_date, end_date):
        logger.info(f'quote ingest start')

        if codes is None:
            codes = self._symbol_index.codes

        fetch_chunk_num = 50
        symbols_len = len(codes)
        all_chunk_num = symbols_len // fetch_chunk_num + 1

        for i in range(0, len(codes), fetch_chunk_num):
            logger.info(f'ingest quote: {i // fetch_chunk_num + 1}/{all_chunk_num}')
            period_codes = codes[i: i+fetch_chunk_num]
            yield StandardQuoteIngester.ingest_daily_hists_quote(period_codes, start_date, end_date)

    def init(self, symbols, start_date, end_date):
        self.load(mode='w+')
        for quote in self.ingest(None, start_date, end_date):
            self.save(quote)

    def update(self, end_date):
        pass

    def save(self, data):
        data['sid'] = sids = data.symbol.apply(self._symbol_index.i_of)
        data['did'] = data.trade_date.apply(self._date_index.i_of)
        data['chunk_id'] = sids // self._chunks_s_num               # 保存到第几块数据
        data['chunk_sid'] = sids % self._chunks_s_num           # 数据symbol在块内的索引
        data.dropna(how='any', inplace=True)
        logger.debug('[daily_bar_util] saving ohlcv:\n %s' % (data,))
        data.drop(columns=['symbol', 'trade_date'], inplace=True)
        data.set_index(['did', 'sid'], inplace=True)

        for field in self._fields_dict.values():
            single_field_data = data[field.name].unstack()
            single_field_data = single_field_data.sort_index().fillna(0)
            start_sid = single_field_data.index[0]
            end_sid = single_field_data.index[-1]
            for sid in single_field_data.columns:
                mmp_obj = self._get_memmap_obj(feild_obj=field, sid=sid)
                mmp_obj[start_sid:end_sid+1, sid % self._chunks_s_num] = \
                    (single_field_data[sid] * field.precision).to_numpy(dtype='int32')

    def _get_memmap_obj(self, feild_obj, sid):
        chunk_id = sid // self._chunks_s_num
        return self._memmap_files_dict[feild_obj][chunk_id]

    def load(self, mode='r+'):
        self._date_index.load()
        self._symbol_index.load()
        self._memmap_files_dict = defaultdict(dict)
        sid_len = len(self._symbol_index.symbols)
        chunk_shape = (len(self._date_index.dates), self._chunks_s_num)
        chunk_num = sid_len // self._chunks_s_num + 1

        ### init memmap
        for field, path in self._fields_dir_path.items():
            for chunk_id in range(chunk_num):
                self._memmap_files_dict[field][chunk_id] = \
                np.memmap(os.path.join(path, f'{chunk_id}.dat'),
                          shape=chunk_shape, dtype='int32', mode=mode)

    def fields_to_obj(self, fields_list):
        return [self._fields_dict[field_name] for field_name in fields_list]

    def get_symbol_data(self, symbol, start_date, end_date, fields_list):
        sid = self._symbol_index.i_of(symbol)
        calendar = self._date_index.get_calendar(start_date, end_date)
        start_id = self._date_index.i_of(start_date)
        end_id = self._date_index.i_of(end_date)
        chunk_sid = sid % self._chunks_s_num

        fields_arr_list = []
        for field_obj in self.fields_to_obj(fields_list):
            mmp_obj = self._get_memmap_obj(feild_obj=field_obj, sid=sid)
            arr = mmp_obj[start_id:end_id+1, chunk_sid] / field_obj.precision
            fields_arr_list.append(arr)

        fields_arr = np.array(fields_arr_list).T
        frame = Frame(fields_arr, calendar, fields_list, symbol)
        return frame

    def get_symbols_data(self, symbols, start_date, end_date, field_list):
        if isinstance(symbols, str):
            symbols = [symbols, ]

        sf = SFrame()
        for symbol in symbols:
            frame = self.get_symbol_data(symbol, start_date, end_date, field_list)
            sf.add(frame)

        return sf
