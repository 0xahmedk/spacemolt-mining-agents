"""Run every offline test: python -m tests.run_all"""
from tests import test_gateway, test_parsers


def main():
    test_parsers.run()
    test_gateway.run()
    print('ALL OFFLINE TESTS PASS')


if __name__ == '__main__':
    main()
