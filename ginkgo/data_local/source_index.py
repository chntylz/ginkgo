# -*- coding:utf-8 -*-
"""
@author: ksf

@since: 2019-11-04 19:18
"""

import os
import pickle
import pandas as pd
from ginkgo.data_local.ingester import StandardQuoteIngester
from ginkgo.core.model import StockContract
from ginkgo.data_local.interface import Index
from ginkgo.utils.logger import logger


class RowDateIndex(Index):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index_path = \
            os.path.join(self._base_path, f'{self._catgory}/{self._market}/meta/row_date_index.plk')
        self.check_file(self._index_path)

    def ingest(self, start_date=None, end_date=None):
        logger.info(f'ingest calendar from {start_date} to {end_date}')
        return StandardQuoteIngester.ingest_calender(start_date, end_date, self._market)

    def init(self, start_date, end_date):
        logger.info(f'init date index {start_date} - {end_date}')
        calendar_list = self.ingest(start_date, end_date)
        self.save(calendar_list)
        self.load()

    def update(self, end_date):
        pass

    def load(self):
        logger.info('loading symbol info')
        with open(self._index_path, mode='rb+') as f:
            self._name_list = pickle.load(f)
        self._name_i_map = {}
        for i, name in enumerate(self._name_list):
            self._name_i_map[name] = i
        self._latest_date = self._name_list[-1]

    def save(self, data):
        logger.info('saving date index')
        with open(self._index_path, 'wb+') as f:
            pickle.dump(data, f)

    def i_of(self, name):
        return self._name_i_map[name]

    def o_of(self, i):
        return self._name_list[i]

    @property
    def dates(self):
        return self._name_list


class ColSymbolIndex(Index):
    def __init__(self, *args, chunks_s_num=300, **kwargs):
        super().__init__(*args, **kwargs)
        self._chunks_s_num = chunks_s_num
        self._index_path = \
            os.path.join(self._base_path, f'{self._catgory}/{self._market}/meta/col_symbol_index.plk')
        self.check_file(self._index_path)
        self._stock_contract_list = []
        self._code_contract_dict = {}
        self._contract_df = None

    def ingest(self):
        logger.info('ingest symbol info')
        return StandardQuoteIngester.ingest_symbols(self._market)

    def init(self):
        logger.info('init symbol info')
        col_df = self.ingest()
        self.save(col_df)
        self.load()

    def save(self, data: pd.DataFrame):
        logger.info('saving symbol info')
        data.to_csv(self._index_path, index=False)

    def load(self):
        logger.info('loading symbol info')
        self._contract_df = pd.read_csv(self._index_path)
        for i, row in self._contract_df.iterrows():
            sc = StockContract(code=row.code, symbol=row.symbol, sid=i, name=row.name, market=self._market,
                               industry=row.industry, board=row.board, area=row.area, list_date=row.list_date)

            self._stock_contract_list.append(sc)
            self._code_contract_dict[row.code] = sc

    def contract_from_code(self, code):
        return self._code_contract_dict[code]

    def i_of(self, name):
        return self.contract_from_code(name).sid

    def o_of(self, i):
        return self._stock_contract_list[i]

    def chunk_id(self, i):
        return i // self._chunks_s_num

    def chunk_sid(self, i):
        return i % self._chunks_s_num

    @property
    def codes(self):
        return list(self._code_contract_dict.keys())

    def contracts_filter(self, industry=None, area=None, board=None):
        if (industry is None) & (area is None) & (board is None):
            return self._stock_contract_list[:]

        industry_mask = True
        area_mask = True
        board_mask = True
        if industry is not None:
            industry_mask = self._contract_df['industry'] == industry
        if area is not None:
            area_mask = self._contract_df['area'] == area
        if board is not None:
            board_mask = self._contract_df['board'] == board

        mask = industry_mask & area_mask & board_mask

        selected = self._contract_df.iloc[mask]['code']
        contracts = []
        for c in selected:
            obj = self.contract_from_code(c)
            contracts.append(obj)
        return contracts
