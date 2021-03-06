from __future__ import absolute_import, division, print_function, unicode_literals

import math
from numbers import Number

import torch
from torch.distributions import constraints
from torch.distributions.utils import broadcast_all
from torch.nn import Module as TModule

from .prior import Prior
from .torch_priors import NormalPrior


class SmoothedBoxPrior(Prior):
    """A smoothed approximation of a uniform prior.

    Has full support on the reals and is differentiable everywhere.

        B = {x: a_i <= x_i <= b_i}
        d(x, B) = min_{x' in B} |x - x'|

        pdf(x) ~ exp(- d(x, B)**2 / sqrt(2 * sigma^2))

    """

    arg_constraints = {"sigma": constraints.positive, "a": constraints.real, "b": constraints.real}
    support = constraints.real
    _validate_args = True

    def __init__(self, a, b, sigma=0.01, log_transform=False, validate_args=False):
        TModule.__init__(self)
        _a = torch.tensor(float(a)) if isinstance(a, Number) else a
        _a = _a.view(-1) if _a.dim() < 1 else _a
        _a, _b, _sigma = broadcast_all(_a, b, sigma)
        if not torch.all(constraints.less_than(_b).check(_a)):
            raise ValueError("must have that a < b (element-wise)")
        # TODO: Proper argument validation including broadcasting
        batch_shape, event_shape = _a.shape[:-1], _a.shape[-1:]
        # need to assign values before registering as buffers to make argument validation work
        self.a, self.b, self.sigma = _a, _b, _sigma
        super(SmoothedBoxPrior, self).__init__(batch_shape, event_shape, validate_args=validate_args)
        # now need to delete to be able to register buffer
        del self.a, self.b, self.sigma
        self.register_buffer("a", _a)
        self.register_buffer("b", _b)
        self.register_buffer("sigma", _sigma)
        self.tails = NormalPrior(torch.zeros_like(_a), _sigma, validate_args=validate_args)
        self._log_transform = log_transform

    @property
    def _c(self):
        return (self.a + self.b) / 2

    @property
    def _r(self):
        return (self.b - self.a) / 2

    @property
    def _M(self):
        # normalization factor to make this a probability distribution
        return torch.log(1 + (self.b - self.a) / (math.sqrt(2 * math.pi) * self.sigma))

    def log_prob(self, parameter):
        return self._log_prob(parameter.exp() if self.log_transform else parameter)

    def _log_prob(self, parameter):
        # x = "distances from box`"
        X = ((parameter - self._c).abs_() - self._r).clamp(min=0)
        return (self.tails.log_prob(X) - self._M).sum(-1)
