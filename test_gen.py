import sys; sys.path.insert(0, r'E:\HACKATHON\flexiee\flexie_v2')
import os
from core.jobs.planner import ProjectFileSpec, ProjectSpec
from core.jobs.models import BuildJob

spec = ProjectSpec(
    title='Test App',
    stack='static-web',
    summary='A simple app',
    run_command='echo run',
    test_command='none',
    dependencies=[],
    files=[
        ProjectFileSpec(name='index.html', purpose='main ui'),
        ProjectFileSpec(name='app.js', purpose='main logic')
    ],
    acceptance_criteria=['It works'],
    phases=[],
    template_used='none'
)
fspec = spec.files[1] # generating app.js
job = BuildJob(title='Job', request_text='...')
job.workspace_path = r'E:\HACKATHON\flexiee\flexie_v2\test_ws_2'
os.makedirs(job.workspace_path, exist_ok=True)
with open(os.path.join(job.workspace_path, 'index.html'), 'w', encoding='utf-8') as f:
    f.write('<html><div id="root"></div></html>\n')

class DummyBrain:
    def ask(self, prompt, **kwargs):
        print('PROMPT START')
        print(prompt)
        print('PROMPT END')
        return 'console.log("hello");'

from core.jobs.generator import CodeGenerator
gen = CodeGenerator()
res, msg = gen.generate_single_file(job, fspec, DummyBrain(), spec)
print('Generated:', res, msg)
