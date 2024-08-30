class Singleton(type):
    # singleton
    _instances = {}

    def __new__(cls, name, bases, dct):
        x = super().__new__(cls, name, bases, dct)
        return x
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton,cls).__call__(*args, **kwargs)
        return cls._instances[cls]