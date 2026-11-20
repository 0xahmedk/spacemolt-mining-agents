"""Offline tests for the Phase 3 store: missions, A2A tasks, pilot leases, observations."""
from pathlib import Path
from tempfile import TemporaryDirectory

from mas.store import IllegalTransition, Store


class Clock:
    """Controllable time so lease expiry and staleness can be tested instantly."""

    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float):
        self.t += seconds


def run():
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / 'state.sqlite3'
        log = str(Path(tmp) / 'events.jsonl')
        clock = Clock()
        st = Store(db_path, agent='coordinator', clock=clock, log_path=log)

        # ---------------------------------------------------------------- missions
        mid = st.missions.create('Complete first_cargo with pilot A', decided_by='llm', pilot='Pilot-A',
                                 rationale='copper deposit 8 left; mission pays 1,000 cr',
                                 constraints={'max_spend': 100}, plan={'game_mission': 'first_cargo'})
        m = st.missions.get(mid)
        assert m['status'] == 'proposed' and m['constraints'] == {'max_spend': 100}, m
        for s in ('assigned', 'in_progress', 'verifying'):
            st.missions.transition(mid, s)
        st.missions.transition(mid, 'done', result={'credits_delta': 1000})
        assert st.missions.get(mid)['result'] == {'credits_delta': 1000}
        try:
            st.missions.transition(mid, 'in_progress')
            raise AssertionError('done -> in_progress must be illegal')
        except IllegalTransition:
            pass
        mid2 = st.missions.create('Sell 10 silicon', decided_by='rule', pilot='Pilot-B')
        assert [x['mission_id'] for x in st.missions.open()] == [mid2]
        print('[PASS] mission state machine (legal path, terminal state, open list)')

        # ---------------------------------------------------------------- tasks
        tid, created = st.tasks.create(mid2, assignee='trading', skill='sell', pilot='Pilot-B',
                                       payload={'item': 'silicon_ore', 'qty': 10}, task_id=f'{mid2}:sell:1')
        again, created2 = st.tasks.create(mid2, assignee='trading', skill='sell', pilot='Pilot-B',
                                          payload={'item': 'silicon_ore', 'qty': 10}, task_id=f'{mid2}:sell:1')
        assert created and not created2 and tid == again, 'same deterministic id must not duplicate'
        st.tasks.mark(tid, 'submitted', a2a_task_id='a2a-xyz')
        st.tasks.mark(tid, 'working')
        assert [t['task_id'] for t in st.tasks.unfinished('trading')] == [tid]
        assert st.tasks.unfinished('resource') == []
        st.tasks.mark(tid, 'completed', result={'sold': 10, 'credits': 100})
        t = st.tasks.get(tid)
        assert t['a2a_task_id'] == 'a2a-xyz' and t['attempts'] == 1 and t['result']['sold'] == 10, t
        try:
            st.tasks.mark(tid, 'working')
            raise AssertionError('completed task must stay completed')
        except IllegalTransition:
            pass
        print('[PASS] A2A task records (idempotent create, status flow, terminal lock)')

        # ---------------------------------------------------------------- leases
        assert st.leases.acquire('Pilot-A', 'resource-agent', ttl=60, task_id='T1')
        assert not st.leases.acquire('Pilot-A', 'trading-agent', ttl=60), 'held lease must block others'
        assert st.leases.acquire('Pilot-A', 'resource-agent', ttl=60), 'holder may re-acquire'
        clock.advance(30)
        assert st.leases.renew('Pilot-A', 'resource-agent', ttl=60)
        assert not st.leases.renew('Pilot-A', 'trading-agent', ttl=60)
        clock.advance(59)
        assert st.leases.holder('Pilot-A') == 'resource-agent'
        clock.advance(2)  # resource agent "crashed": lease expired
        assert st.leases.holder('Pilot-A') is None
        assert st.leases.acquire('Pilot-A', 'trading-agent', ttl=60), 'expired lease can be taken over'
        assert not st.leases.release('Pilot-A', 'resource-agent'), 'only the holder may release'
        assert st.leases.release('Pilot-A', 'trading-agent')
        print('[PASS] pilot leases (exclusive, renew, expiry takeover, holder-only release)')

        # ---------------------------------------------------------------- observations
        st.observations.record('Pilot-A', 'status', {'credits': 250, 'fuel': 130}, 'spacemolt.get_status')
        clock.advance(5)
        st.observations.record('Pilot-A', 'status', {'credits': 260, 'fuel': 129}, 'spacemolt.get_status')
        assert st.observations.fresh('Pilot-A', 'status', max_age=30) == {'credits': 260, 'fuel': 129}
        clock.advance(31)
        assert st.observations.fresh('Pilot-A', 'status', max_age=30) is None, 'stale data must be refused'
        assert st.observations.latest('Pilot-A', 'status')['age'] == 31
        assert st.observations.fresh('Pilot-B', 'status', max_age=30) is None
        print('[PASS] observations (latest wins, stale refused)')

        st.close()

        # ---------------------------------------------------------------- restart
        st2 = Store(db_path, agent='coordinator-restarted', clock=clock, log_path=log)
        assert st2.missions.get(mid)['status'] == 'done'
        assert [x['mission_id'] for x in st2.missions.open()] == [mid2]
        assert st2.tasks.get(tid)['status'] == 'completed'
        assert st2.observations.latest('Pilot-A', 'status')['data']['credits'] == 260
        st2.close()
        print('[PASS] everything survives a process restart')

        # ---------------------------------------------------------------- two processes
        a = Store(db_path, agent='proc-a', clock=clock, log_path=log)
        b = Store(db_path, agent='proc-b', clock=clock, log_path=log)
        wins = [a.leases.acquire('Pilot-B', 'proc-a', ttl=60), b.leases.acquire('Pilot-B', 'proc-b', ttl=60)]
        assert wins == [True, False], wins
        a.close()
        b.close()
        print('[PASS] two connections: only one gets the pilot lease')


if __name__ == '__main__':
    run()
