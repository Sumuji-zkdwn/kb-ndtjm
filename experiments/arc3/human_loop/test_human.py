import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import numpy as np
import data
import engine
import models


def observation(action, level=0, frame=0, state='NOT_FINISHED'):
    return {'action_input': {'id': action}, 'levels_completed': level, 'frame': [[[frame]]],
            'available_actions': [1, 2, 3, 4], 'state': state, 'game_id': 'fixture-v1'}


def fixture_dataset(folder):
    folder.mkdir(); arrays={}
    rng=np.random.default_rng(3)
    for domain in data.DOMAINS:
        k=models.CARDINALITY[domain]; a=[]; d=[]
        for group in range(10):
            for i in range(24):
                a.append([i%k, i%4, i%4, group%2, (i+group)%k, group])
                d.append([float(np.exp(rng.normal(2, 1))), int(i%5!=0), i%4, group%2, group])
        arrays[domain+'_actions']=np.array(a,dtype=np.int32)
        arrays[domain+'_durations']=np.array(d,dtype=float)
    np.savez_compressed(folder/'observations.npz',**arrays)
    data.save_json(folder/'manifest.json', {'schema':data.SCHEMA,'observations_sha256':data.digest(folder/'observations.npz')})
    return arrays


class Observations(unittest.TestCase):
    def test_future_frame_cannot_change_preceding_predictors(self):
        left=[observation(0),observation(1),observation(2,1,5,'WIN')]
        right=copy.deepcopy(left);right[-1]['frame']=[[[9]]]
        a, d, _=data.arc_session(left,0); aa,dd,_=data.arc_session(right,0)
        self.assertEqual(a,aa);self.assertEqual(d,dd)
        self.assertEqual(d[0][:2],[2,1])

    def test_reset_does_not_erase_effort(self):
        rows=[observation('RESET'),observation('ACTION1'),observation('RESET'),observation('ACTION2',1,0,'WIN')]
        _,d,_=data.arc_session(rows,0)
        self.assertEqual(d[0][:2],[3,1])

    def test_unsolved_attempt_is_censored(self):
        _,d,_=data.arc_session([observation(0),observation(1),observation(2)],0)
        self.assertEqual(d[0][:2],[2,0])

    def test_scorecard_footer_is_not_an_action(self):
        lines=[{'data':observation(0)}, {'data':{'cards':{},'total_actions':0}}]
        self.assertEqual(len(list(data.arc_records(io.BytesIO('\n'.join(map(json.dumps,lines)).encode())))),1)
        with self.assertRaises(ValueError):list(data.arc_records(io.BytesIO(b'{"data":{"unknown":1}}')))

    def test_xstream_relative_reference_identity(self):
        root=ET.fromstring('<root><item><id><uuid>same</uuid></id></item><item><id reference="../../item/id"/></item></root>')
        parents={c:p for p in root.iter() for c in p}
        self.assertEqual(data.resolve_reference(root[1][0],parents).findtext('uuid'),'same')

    def test_janssen_chat_and_addresses_not_in_normalized_output(self):
        xml=b'''<object-stream><sorted-set>
        <edu.asu.commons.foraging.event.MovementEvent><id><uuid>secret-person</uuid><address>secret-address</address></id><creationTime>1000</creationTime><direction>UP</direction></edu.asu.commons.foraging.event.MovementEvent>
        <edu.asu.commons.event.ChatEvent><message>private-chat</message></edu.asu.commons.event.ChatEvent>
        <edu.asu.commons.foraging.event.TokenCollectedEvent><id reference="../../edu.asu.commons.foraging.event.MovementEvent/id"/><creationTime>2000</creationTime></edu.asu.commons.foraging.event.TokenCollectedEvent>
        </sorted-set></object-stream>'''
        a,d,people,ties=data.janssen_round(xml,0,1,1)
        self.assertEqual((len(a),len(d),people,ties),(2,1,1,0))
        self.assertEqual(a[1][0],0);self.assertEqual(a[1][4],4)
        self.assertNotIn('secret',json.dumps([a,d]))


class Distributions(unittest.TestCase):
    def test_censored_likelihood_is_survival_not_event_mass(self):
        p=np.array([.2,.3,.5]);ev=np.array([0.,0,0]);ce=np.array([0.,1,0])
        self.assertAlmostEqual(models.censor_nll(p,ev,ce),-np.log(.8))

    def test_censoring_retains_right_tail(self):
        p=models.empirical(np.array([5.,1,0]),np.array([0.,0,20.]),np.ones(3)*.1)
        self.assertGreater(p[2],.7);self.assertAlmostEqual(p.sum(),1.)

    def test_all_distribution_families_normalize_with_extreme_parameters(self):
        spec=engine.initial_spec(4)
        for family in models.FAMILIES[1:]:
            for mu in (-12.,18.):
                p=models.parametric([mu,-3.],family,'arc',spec)
                self.assertTrue(np.isfinite(p).all());self.assertTrue((p>0).all());self.assertAlmostEqual(p.sum(),1.)

    def test_unknown_condition_uses_training_fallback(self):
        spec=engine.initial_spec(1)
        rows=np.array([[8,0,0,0,1,0],[1,0,0,0,1,0]],dtype=int)
        m=models.fit_action(rows,'arc',spec);rows[:,3]=100
        p=models.predict_action(m,rows)
        np.testing.assert_allclose(p.sum(axis=1),1.)

    def test_group_split_has_no_overlap(self):
        s=engine.split_groups(np.repeat(np.arange(20),10),3)
        self.assertEqual(set(sum(s.values(),[])),set(range(20)))
        self.assertEqual(sum(map(len,s.values())),20)

    def test_unused_energy_parameters_do_not_create_a_new_hypothesis(self):
        a=engine.initial_spec(0);b=dict(a,curvature=4.,beta=2.,energy_input=2.)
        self.assertEqual(engine.effective_identity(a),engine.effective_identity(b))
        a['family']='quartic';b['family']='quartic'
        self.assertNotEqual(engine.effective_identity(a),engine.effective_identity(b))

    def test_worse_distinct_forecast_is_retained(self):
        def record(i,loss,signature):
            metric={'group_macro_nll':loss,'condition_nll':{'0':loss}}
            return {'id':i,'status':'complete','signature':signature,
                    'validation':{d:{'action':metric,'duration':metric} for d in data.DOMAINS}}
        p=engine.portfolio([record('best',1,[.5,.5]),record('different',3,[.01,.99])])
        self.assertEqual(p['pareto'],['best']);self.assertIn('different',p['retained'])

    def test_validated_forecasts_do_not_read_test_targets(self):
        with tempfile.TemporaryDirectory() as t:
            arrays=fixture_dataset(Path(t)/'data')
            splits={d:engine.split_groups(arrays[d+'_actions'][:,5],11) for d in data.DOMAINS}
            a=engine.fit_candidate(engine.initial_spec(0),arrays,splits)
            for domain in data.DOMAINS:
                rows=arrays[domain+'_actions']; mask=np.isin(rows[:,5],splits[domain]['test'])
                rows[mask,4]=(rows[mask,4]+1)%models.CARDINALITY[domain]
                rows=arrays[domain+'_durations']; rows[np.isin(rows[:,4],splits[domain]['test']),0]*=1000
            b=engine.fit_candidate(engine.initial_spec(0),arrays,splits)
            self.assertEqual(a,b)


class Control(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        fixture_dataset(self.root/'data')
    def tearDown(self):self.temp.cleanup()

    def test_stop_resume_seal_and_refusal_to_tune_test(self):
        out=self.root/'run';out.mkdir();(out/'STOP').touch()
        s=engine.run(self.root/'data',out,candidates=2)
        self.assertEqual(len(s['records']),0)
        (out/'STOP').unlink()
        engine.run(self.root/'data',out,candidates=1)
        s=engine.run(self.root/'data',out,candidates=1)
        self.assertEqual(len(s['records']),2)
        r=engine.seal(self.root/'data',out)
        self.assertIn('uniform_portfolio_test',r)
        self.assertEqual(engine.seal(self.root/'data',out),r)
        with self.assertRaisesRegex(ValueError,'sealed'):engine.run(self.root/'data',out)
        f=engine.forecast(out,4,16)
        self.assertTrue(0<=f['human_progress_probability']<=1)

    def test_candidate_tampering_detected_on_resume(self):
        out=self.root/'run';engine.run(self.root/'data',out)
        f=out/'candidates/h00000/models.json';f.write_text('{}')
        with self.assertRaisesRegex(ValueError,'model changed'):engine.run(self.root/'data',out)

    def test_input_tampering_detected(self):
        f=self.root/'data/observations.npz'
        with f.open('ab') as stream:stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'identity'):engine.load_data(self.root/'data')

    def test_finite_budget_required(self):
        with self.assertRaises(ValueError):engine.run(self.root/'data',self.root/'r',candidates=0)

    def test_deterministic_continuation_matches_initial_schedule(self):
        records=[]
        for i in range(10):
            spec,_=engine.propose(records,5)
            self.assertEqual(spec,engine.initial_spec(i))
            records.append({'spec':spec})


if __name__=='__main__':unittest.main(verbosity=2)
