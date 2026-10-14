from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
if (root/'.env').exists():
    print('Existing .env retained.')
else:
    password=secrets.token_hex(16)
    text=(root/'.env.example').read_text().replace('CHANGE_ME',password).replace('GENERATE_A_RANDOM_SECRET',secrets.token_hex(32)).replace('@localhost:','@127.0.0.1:')
    (root/'.env').write_text(text)
    roles=['engineer', 'commander', 'viewer']
    (root/'LOGIN.txt').write_text('Local accounts:\n'+'\n'.join(role+'@local.demo' for role in roles)+'\nPassword: '+password+'\n')
    print('Created .env and private LOGIN.txt.')
