"""Generate one deterministic S04 business fixture from the existing Python scenario model.
This is test input, not evidence that the Java service applied it.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/factory-simulator'))
from factory_simulator.model import FactoryModel
from factory_simulator.run_configuration import RunConfiguration
from factory_simulator import scenario_demo

NOW=datetime(2026,10,5,9,tzinfo=timezone.utc)
# Freeze only the test input clock; physical transitions still use the actual S02 model.
scenario_demo.FactoryModel=lambda config:FactoryModel(config,clock=lambda:NOW)
result=scenario_demo.demo_scenarios(RunConfiguration.from_path())
path=ROOT/'services/operations-service/src/test/resources/factory-scenario.ndjson'
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(''.join(json.dumps(e,ensure_ascii=False,separators=(',',':'))+'\n' for e in result['events']))
print('Generated S04 fixture:',len(result['events']),'model events; Java/DB verification is separate.')
