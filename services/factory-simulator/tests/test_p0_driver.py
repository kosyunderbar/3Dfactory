import unittest
from factory_simulator.model import FactoryModel
from factory_simulator.p0_demo import P0Driver
from factory_simulator.run_configuration import RunConfiguration

class P0DriverTests(unittest.TestCase):
    def test_registered_flow_reaches_full_pickup_transit_arrival_release_and_unique_quality(self):
        config=RunConfiguration.from_path().to_dict()
        for item in config['config']['equipment']:item['workDurationMs']=200
        for route in config['config']['routes']:route['travelDurationMs']=1000
        model=FactoryModel(RunConfiguration.from_dict(config),quality_results=('FAIL','PASS','PASS','PASS','PASS'))
        driver=P0Driver(model);change=lambda method,*args:method(*args)
        driver.initialize(change);stages=[]
        for _ in range(3000):
            stage=driver.step(change)
            if stage:
                while stage:
                    snapshot=model.snapshot();bay=next(b for b in snapshot['buffers'] if b['cellId']=='ASM-02')
                    stages.append(stage)
                    if stage in ('FULL_RESERVED','FULL_IN_TRANSIT'):
                        self.assertEqual((bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots']),(2,1,0))
                        trip=next(t for t in snapshot['activeTransports'] if t['destination']['locationId']=='BAY-ASM-02')
                        body=next(b for b in snapshot['bodies'] if b['bodyId']==trip['bodyId'])
                        self.assertEqual(body['locationType'],'CELL' if stage=='FULL_RESERVED' else 'VEHICLE')
                    if stage=='FULL_ARRIVED':self.assertEqual((bay['waitingCount'],bay['reservedInboundCount'],bay['availableSlots']),(3,0,0))
                    if stage=='CELL_DOWN':self.assertEqual(model.cell('ASM-01').state.value,'DOWN')
                    if stage=='SLOT_RELEASED':
                        self.assertEqual(bay['waitingCount'],2)
                        self.assertEqual(model.cell_entries[-1].available_slots_after_release,1)
                    stage=driver.after(stage,change)
            if driver.drained():break
        else:self.fail('P0 stages did not drain')
        self.assertEqual(stages,['FULL_RESERVED','FULL_IN_TRANSIT','FULL_ARRIVED','CELL_DOWN','SLOT_RELEASED'])
        self.assertEqual(len(model.operations),15);self.assertEqual(len(model.inspections),5)
        self.assertEqual(sum(i.result.value=='FAIL' for i in model.inspections),1)
        self.assertEqual(len({b.body_id for b in model.bodies}),5)
        model.finish_run();self.assertEqual(model.snapshot()['runState'],'FINISHED')

    def test_paused_snapshot_reports_without_advancing_resuming_or_exceeding_budget(self):
        from datetime import datetime,timezone
        from factory_simulator.configuration import Settings
        from factory_simulator.sender import Sender,SourceSession
        model=FactoryModel(RunConfiguration.from_path(),clock=lambda:datetime(2026,10,5,tzinfo=timezone.utc))
        sender=Sender(Settings('127.0.0.1',9090));session=SourceSession(model,sender)
        session.change(model.register_body);session.pause();before=model.snapshot()
        observation=session.change(model.publish_snapshot)
        self.assertEqual(observation.to_dict()['payload']['runState'],'PAUSED')
        self.assertEqual(model.snapshot(),before);self.assertFalse(session.automatic_pause)
        self.assertIsNone(session.tick());self.assertEqual(model.snapshot(),before)
        sender.pending.enqueue_originals([sender.pending.head]*(900-len(sender.pending)))
        seq=model.events[-1].to_dict()['sourceSeq']
        self.assertIsNone(session.change(model.publish_snapshot))
        self.assertEqual(len(sender.pending),900);self.assertEqual(model.events[-1].to_dict()['sourceSeq'],seq)
        self.assertFalse(session.automatic_pause);sender.close()
