"""Run every offline test: python -m tests.run_all"""
from tests import test_coordinator, test_gateway, test_parsers, test_store, test_workers


def main():
    test_parsers.run()
    test_gateway.run()
    test_store.run()
    test_workers.run()
    test_coordinator.run()
    print('ALL OFFLINE TESTS PASS')


if __name__ == '__main__':
    main()
