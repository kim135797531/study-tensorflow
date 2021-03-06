# -*- coding: utf-8 -*-

import time
from collections import defaultdict

import numpy as np
import torch

import utils_kdm as u
from utils_kdm import TorchSerializable
from utils_kdm.manage_device import ManageDevice
from utils_kdm.singleton import Singleton


def _make_indicator_defaultdict():
    return defaultdict(_make_indicator_inner_defaultdict)


def _make_indicator_inner_defaultdict():
    return defaultdict(list)


# noinspection PyMethodParameters
class TrainerMetadata(TorchSerializable, Singleton):

    def __init__(cls):
        super().__init__()

        # 내부 사용 인스턴스
        cls.viz = None
        cls.checkpoint = None
        cls.agent = None

        # 내부 사용 변수
        cls.current_epoch = None
        cls.global_step = None

        cls.indicators = None
        cls._last_only_indicators = None
        cls._temp_for_maxmin_indicators = None
        cls.best_score = None

        cls.start_time = 0

        # 환경 설정
        cls.log_interval = None
        cls.save_full_path = None

        cls.register_serializable([
            'current_epoch',
            'global_step',
            'indicators',
            'best_score',
            'agent',
        ])

        cls.console_indicators = dict()
        cls.console_log_order = list()

    @property
    def device(cls):
        return ManageDevice().get(call_from='TrainerMetadata')

    def reset(cls,
              viz,
              checkpoint,
              agent,
              force_cpu=False,
              log_interval=1,
              save_full_path=__file__,
              visdom_order=None,
              console_log_order=None):
        cls.viz = viz
        cls.checkpoint = checkpoint
        cls.agent = agent

        cls.current_epoch = 0
        cls.global_step = 0

        # Indicators는 화면에 표시도 하고 저장/불러오기 할 지표들
        cls.indicators = _make_indicator_defaultdict()

        # 단순히 맨 마지막에 들어온 값으로 덮어씌워가면서 유지
        # 한 에피소드가 끝나면 indicators로 자료 옮기기
        cls._last_only_indicators = defaultdict(dict)

        # 전부 다 저장하는 곳
        # 한 에피소드가 끝나면 Max, Min 값 등을 구해서 indicators로 자료 옮기기
        # 이 안을 출력하는 것은 아니다 (할 거면 진작에 log() 메소드에서 출력함)
        cls._temp_for_maxmin_indicators = _make_indicator_defaultdict()

        cls.best_score = 0

        cls.start_time = 0
        cls.log_interval = log_interval
        cls.save_full_path = save_full_path

        if visdom_order is not None and type(visdom_order) is list:
            viz.set_visdom_order(viz.default_env, visdom_order)

        if console_log_order is not None and type(console_log_order) is list:
            cls.console_log_order.extend(console_log_order)

        ManageDevice().set(force_cpu, call_from='TrainerMetadata')

    def set_device(cls, force_cpu=False):
        ManageDevice().set(force_cpu, call_from='TrainerMetadata')

    def log(cls, value=0, indicator='default_win', variable='default_var', interval=1, show_only_last=True, compute_maxmin=False):
        value = u.maybe_float(value)
        if cls.global_step % interval == 0:
            if show_only_last:
                # 맨 마지막 값만 유지
                cls._last_only_indicators[indicator][variable] = value
            else:
                # 전부 표시 (실시간)
                # visdom에 x축을 auto-increment 하는 기능이 없어서 내가 만든 wrapper 메소드 사용
                value = u.maybe_float(value)
                cls.viz.draw_line(y=value, x=None, x_auto_increment='per_variable_step', win=indicator, variable=variable)

            if compute_maxmin:
                # 한 에피소드 당 변수의 최대/평균/최소 등을 계산하기 위해 저장
                cls._temp_for_maxmin_indicators[indicator][variable].append(value)

    def console_log(cls, name, value):
        cls.console_indicators[name] = value
        # 명시적으로 log 요청했는데도 order에 없는 경우, order 맨 뒤에 추가
        if name not in cls.console_log_order:
            cls.console_log_order.append(name)

    def save(cls):
        # state_dict 구성 속도가 느리므로 필요할 때만 구성
        if cls.checkpoint.is_saving_episode(cls.current_epoch):
            var_state = cls.state_dict()
            is_best = False
            if 'score' in cls.indicators:
                score = cls.indicators['score']['default_var']
                max_score = max(score)
                if max_score > cls.best_score:
                    cls.best_score = max_score
                    is_best = True

            cls.checkpoint.save_checkpoint(cls.save_full_path, var_state, is_best)

    def load(cls):
        full_path = cls.checkpoint.get_best_model_file_name(cls.save_full_path)
        print("Loading checkpoint '{}'".format(full_path))
        var_state = cls.checkpoint.load_model(full_path=full_path)
        cls.load_state_dict(var_state)

        for indicator_name, variables in cls.indicators.items():
            for variable_name, variable_sequence in variables.items():
                for i_episode in range(0, len(variable_sequence)):
                    y = u.maybe_float(variable_sequence[i_episode])
                    cls.viz.draw_line(x=i_episode, y=y,
                                      win=indicator_name, variable=variable_name)

        print("Loading complete. Resuming from episode: {}".format(cls.current_epoch - 1))
        if 'score' in cls.indicators:
            score = cls.indicators['score']['default_var'][-1]
            print("Score: {:.2f}".format(max(score, default=0)))

    def start_episode(cls):
        cls.start_time = time.time()

    def start_step(cls):
        cls.global_step += 1

    def finish_step(cls):
        pass

    def _fill_if_empty(cls, format_str, name, value):
        if name not in cls.console_indicators:
            cls.console_indicators[name] = format_str.format(value)

    def _fill_default_console_indicators(cls):
        cls._fill_if_empty('{}', 'Epoch', cls.current_epoch)
        cls._fill_if_empty('{:.2f}', 'Score', u.maybe_float(cls.indicators['score']['default_var'][-1]))
        cls._fill_if_empty('{:.2f}', 'Time', time.time() - cls.start_time)

        for name in cls.console_log_order:
            cls._fill_if_empty('{}', name, 'N/A')

    def finish_episode(cls, i_episode):
        cls.current_epoch = i_episode

        for indicator_name, variables in cls._last_only_indicators.items():
            for variable_name, variable in variables.items():
                cls.indicators[indicator_name][variable_name].append(variable)

        for indicator_name, variables in cls._temp_for_maxmin_indicators.items():
            for variable_name, variable_sequence in variables.items():
                # TODO: 그냥 max 써도 되나? torch.max?
                # TODO: mean 일반화
                # TODO: 사용자 정의 지표는?
                val_max = max(variable_sequence)
                val_min = min(variable_sequence)
                cls.indicators[indicator_name]['max'].append(val_max)
                cls.indicators[indicator_name]['min'].append(val_min)
                # 맨 마지막 값은 나중에 불러오기 할 때 개략적으로나마 표시해 주기 위해
                # cls.indicators[indicator_name][variable_name].append(variable_sequence[-1])

        cls._fill_default_console_indicators()

        if i_episode % cls.log_interval == 0:
            for name in cls.console_log_order:
                print('{}: {}\t'.format(name, str(cls.console_indicators[name])), end='')
            print('')

            for indicator_name, variables in cls.indicators.items():
                if 'memory' in indicator_name:
                    continue

                for variable_name, variable in variables.items():
                    y = u.maybe_float(variable[-1])
                    cls.viz.draw_line(x=i_episode, y=y, win=indicator_name, variable=variable_name)

            cls._last_only_indicators.clear()
            cls._temp_for_maxmin_indicators.clear()
            cls.console_indicators.clear()
