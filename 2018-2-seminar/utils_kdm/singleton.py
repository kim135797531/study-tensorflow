# -*- coding: utf-8 -*-


#####################
# Python 싱글턴 구현
#####################
class _Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            # noinspection PyArgumentList
            cls._instances[cls] = \
                super(_Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Singleton(
    _Singleton(
        'SingletonMeta',
        (object,),
        {}
    )
):
    pass
