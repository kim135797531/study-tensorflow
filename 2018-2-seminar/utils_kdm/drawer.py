# -*- coding: utf-8 -*-
from collections import defaultdict

import numpy as np
from visdom import Visdom

from utils_kdm.trainer_metadata import TrainerMetadata


class Drawer:

    def __init__(self, reset=False, env='main'):
        if reset:
            Visdom().delete_env(env=env)

        self.default_env = env
        self.default_interval = 1
        self.default_win = 'default_win'
        self.default_variable = 'default_var'

        # 필요할 시 변수별로 스텝 저장
        self.per_variable_step = defaultdict(int)

        self.viz = Visdom(env=env)

    def _abbreviate_win_name(self, env, win):
        env = env if env else self.default_env
        return "{}...{}".format(env[:6], win)

    def set_visdom_order(self, env, visdom_order):
        # TODO: 아직 visdom에 사용자 지정 순서를 지정할 수가 없어서,
        # 일단 더미 데이터로 각각 한 번씩 호출함으로서 그래프 창들 순서대로 초기화
        for win in visdom_order:
            win = self._abbreviate_win_name(env, win)
            self.viz.line(X=np.array([0]), Y=np.array([0]), name='temp_for_order', win=win, update='append', opts={'title': win})
            # self.viz.line(X=np.array([0]), Y=np.array([0]), name='temp_for_order', win=win, update='remove')

    def draw_line(self, y, x=None, x_auto_increment=None, interval=None, env=None, win=None, variable=None):
        if x is None or x == 0:
            if x_auto_increment == 'global_step':
                x = TrainerMetadata().global_step
            elif x_auto_increment == 'per_variable_step':
                x = self.per_variable_step[win]
                self.per_variable_step[win] += 1

        interval = interval if interval else self.default_interval
        env = env if env else self.default_env
        win = win if win else self.default_win
        variable = variable if variable else self.default_variable

        if x % interval == 0:
            # Visdom은 numpy array를 입력으로 받음
            x = x if isinstance(x, np.ndarray) else np.array([x])
            y = y if isinstance(y, np.ndarray) else np.array([y])

            win = self._abbreviate_win_name(env, win)
            self.viz.line(X=np.array([x]), Y=np.array([y]), name=variable, win=win, update='append', opts={'title': win})
