import unittest
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator.traffic import traffic_configuration
from factory_simulator.parts_supply import supply_configuration, snapshot
from factory_simulator.model import FactoryModel, CellState
from factory_simulator.maintenance import ManualMaintenance
from factory_simulator.lane_traffic import final_return_complete


class PartsSupplyTests(unittest.TestCase):
    def model(self, initial=2):
        data=supply_configuration(traffic_configuration(RunConfiguration.from_path())).to_dict()
        data['config']['partsSupply']['initialStock']=initial
        return FactoryModel(RunConfiguration.from_dict(data),quality_results=('PASS',))

    def drive(self, count, initial=2, fault=False):
        model=self.model(initial)
        maintenance=ManualMaintenance(model,lambda fn,*args:fn(*args)) if fault else None
        for _ in range(count):model.register_body()
        model.redispatch()
        for _ in range(24000):
            model.tick()
            if maintenance:
                maintenance.step()
                f=maintenance.fault
                if f and f['stage']=='DETECTED' and model.sim_elapsed_ms-f['occurredMs']>15000:
                    maintenance.command(dict(requestId='inspect',runId=model.run_id,faultId=f['faultId'],action='inspect'))
                elif f and f['stage']=='INSPECTING':
                    maintenance.command(dict(requestId='repair',runId=model.run_id,faultId=f['faultId'],action='repair'))
            for stock in snapshot(model):
                self.assertEqual(stock['available']+stock['consumed'],stock['initialStock']+stock['delivered'])
                self.assertLessEqual(stock['available']+stock['inbound'],stock['capacity'])
            for v in model.vehicles:
                if v.kind=='AMR':self.assertLess(v.y,0)
                else:self.assertGreaterEqual(v.y,0)
            if all(b.location.location_type.value=='RESULT' for b in model.bodies) and not model.active_transports and all(v.state.value=='IDLE' for v in model.vehicles) and final_return_complete(model): break
        else:self.fail('Supply run did not drain')
        self.assertEqual([s['consumed'] for s in snapshot(model)],[count,count])
        self.assertEqual(model.vehicles[-1].y,-240)
        if maintenance:self.assertEqual(maintenance.fault['stage'],'RESOLVED')
        return model

    def test_three_and_ten_bodies_have_no_parts_bottleneck(self):
        for count in (3,10):
            model=self.drive(count)
            self.assertEqual([s['stockoutMs'] for s in snapshot(model)],[0,0])
            self.assertEqual([s['delivered'] for s in snapshot(model)],[count-2,count-2])

    def test_empty_inventory_really_waits_for_physical_delivery(self):
        model=self.model(initial=0)
        for _ in range(3):model.register_body()
        self.assertFalse(model._cell_accepts_delivery('ASM-01'))
        model.redispatch()
        model.advance(1000)
        self.assertEqual(model.operations,())
        self.assertEqual(snapshot(model)[0]['available'],0)
        completed=self.drive(3,initial=0)
        self.assertGreater(sum(s['stockoutMs'] for s in snapshot(completed)),0)

    def test_manual_fault_does_not_consume_twice_or_overstock(self):
        model=self.drive(5,fault=True)
        self.assertEqual([s['stockoutMs'] for s in snapshot(model)],[0,0])
        self.assertEqual(len([t for t in model.transports if t.cargo_type=='PARTS']),6)

    def test_full_dock_rejects_assignment_without_allocating_ids(self):
        model=self.model()
        kits=model.parts
        self.assertFalse(model.assign_parts('ASM-01').approved)
        self.assertEqual(model.parts,kits)
        self.assertEqual(model.transports,())
