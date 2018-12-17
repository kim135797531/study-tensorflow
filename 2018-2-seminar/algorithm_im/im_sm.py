# -*- coding: utf-8 -*-

import torch
import torch.nn as nn
# noinspection PyPep8Naming
import torch.nn.functional as F
import torch.optim as optim

import utils_kdm as u
from algorithm_im.im_base import IntrinsicMotivation
from utils_kdm.trainer_metadata import TrainerMetadata


class StatePredictor(nn.Module):

    def __init__(self, state_size, action_size):
        super(StatePredictor, self).__init__()
        # TODO: 상태 예측은 망 별로 안 커도 학습될 듯? (상태 예측만 테스트 해 보기)
        # 내발적 동기를 위해서 상태를 예측한다는 개념 = 2007년 Oudeyer 논문을 참조한 것
        sensorimotor_size = state_size + action_size
        self.layer_sizes = [sensorimotor_size, 32, 16, state_size]

        self.linear1 = nn.Linear(self.layer_sizes[0], self.layer_sizes[1])
        self.linear2 = nn.Linear(self.layer_sizes[1], self.layer_sizes[2])
        self.head = nn.Linear(self.layer_sizes[2], self.layer_sizes[3])
        u.fanin_init(self.linear1.weight)
        u.fanin_init(self.linear2.weight)
        nn.init.uniform_(self.head.weight, a=-3*10e-4, b=3*10e-4)

    def forward(self, state, action):
        # 그냥 일렬로 합쳐기
        # Oudeyer (2007)
        x = torch.cat((state, action), dim=1)
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        return self.head(x)


class MetaPredictor(nn.Module):

    def __init__(self, state_size, action_size):
        super(MetaPredictor, self).__init__()
        sensorimotor_size = state_size + action_size
        self.layer_sizes = [sensorimotor_size, 32, 16, 1]

        self.linear1 = nn.Linear(self.layer_sizes[0], self.layer_sizes[1])
        self.linear2 = nn.Linear(self.layer_sizes[1], self.layer_sizes[2])
        self.head = nn.Linear(self.layer_sizes[2], self.layer_sizes[3])
        u.fanin_init(self.linear1.weight)
        u.fanin_init(self.linear2.weight)
        nn.init.uniform_(self.head.weight, a=-3*10e-4, b=3*10e-4)

    def forward(self, state, action):
        # 그냥 일렬로 합쳐기
        # Oudeyer (2007)
        x = torch.cat((state, action), dim=1)
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        return self.head(x)


class PredictiveSurpriseMotivation(IntrinsicMotivation):

    def __init__(self, state_size, action_size):
        super().__init__(state_size, action_size)
        self._set_hyper_parameters()

        # Expert Network: (s, a') => (s+1')
        self.expert = StatePredictor(self.state_size, self.action_size).to(self.device)
        self.meta_predictor = MetaPredictor(self.state_size, self.action_size).to(self.device)

        self.expert_optimizer = optim.Adam(
            self.expert.parameters(),
            lr=self.learning_rate_expert
        )
        self.meta_predictor_optimizer = optim.Adam(
            self.meta_predictor.parameters(),
            lr=self.learning_rate_meta_predictor
        )

    def _set_hyper_parameters(self):
        super()._set_hyper_parameters()

        # Expert망 Adam 학습률
        self.learning_rate_expert = 0.001
        # 메타망 Adam 학습률
        self.learning_rate_meta_predictor = 0.001

        # TODO: 적절한 C는 내가 찾아야 함 (일단 알고리즘 밖에서 전체 decay 중)
        self.intrinsic_scale_1 = 1

    def state_dict_impl(self):
        todo = super().state_dict_impl()
        # TODO: 저장 불러오기
        todo = {
            'expert': self.expert.state_dict(),
            'expert_optimizer': self.expert_optimizer.state_dict(),
            'intrinsic_scale_1': self.intrinsic_scale_1
        }
        return todo

    def load_state_dict_impl(self, var_state):
        super().load_state_dict(var_state)
        # TODO: 저장 불러오기
        self.expert.load_state_dict(var_state['expert'])
        self.expert_optimizer.load_state_dict(var_state['expert_optimizer'])
        # noinspection PyAttributeOutsideInit
        self.intrinsic_scale_1 = var_state['intrinsic_scale_1']

    def _train_model(self, state_batch, action_batch, next_state_batch):
        # 상태 예측기 #
        predicted_state_batch = self.expert(state_batch, action_batch)

        # TODO: 상태 예측기도 DDPG 처럼 타겟망까지 만들어서 예측? 아니면 단순한 순차 선형 신경망?
        state_prediction_error = nn.L1Loss(reduction='none').to(self.device)
        state_prediction_error = state_prediction_error(predicted_state_batch.detach(), next_state_batch.detach())
        state_prediction_error = torch.sum(state_prediction_error, dim=1).to(self.device)

        # 상태 예측기 최적화
        self.expert_optimizer.zero_grad()
        state_predictor_loss = nn.MSELoss().to(self.device)  # 배치니까 mean 해줘야 할 듯?
        state_predictor_loss = state_predictor_loss(predicted_state_batch, next_state_batch)
        state_predictor_loss.backward()
        self.expert_optimizer.step()

        # 메타망 #
        predicted_state_predictor_loss = self.meta_predictor(state_batch, action_batch)

        meta_prediction_error = nn.L1Loss(reduction='none').to(self.device)
        meta_prediction_error = meta_prediction_error(predicted_state_predictor_loss.squeeze().detach(), state_prediction_error.detach())
        meta_prediction_error = torch.sum(meta_prediction_error).to(self.device)

        # 메타 최적화
        self.meta_predictor_optimizer.zero_grad()
        meta_predictor_loss = nn.MSELoss().to(self.device)
        meta_predictor_loss = meta_predictor_loss(predicted_state_predictor_loss.squeeze(), state_prediction_error)
        meta_predictor_loss.backward()
        self.meta_predictor_optimizer.step()

        return state_prediction_error, meta_prediction_error

    def intrinsic_motivation_impl(self, i_episode, step, batch_tuple, current_sars, current_done):
        # Predictive Surprise Motivation (SM)
        transitions, state_batch, action_batch, reward_batch, next_state_batch = batch_tuple
        state_prediction_error, meta_prediction_error = self._train_model(state_batch, action_batch, next_state_batch)
        intrinsic_reward_batch = self.intrinsic_scale_1 * (state_prediction_error / meta_prediction_error)

        # TODO: 환경 평소 보상 (1) 정도로 clip 해줄까?
        # intrinsic_reward_batch = torch.clamp(intrinsic_reward_batch, min=-2, max=2)

        # TODO: 제일 처음 Expert망이 조금 학습된 다음에 내발적 동기 보상 리턴하기?
        if self.delayed_start and (TrainerMetadata().global_step < i_episode + self.intrinsic_reward_start):
            return 0

        return intrinsic_reward_batch
