"""Espelha uma referência em dois remotos e tenta reverter falhas parciais."""
import os
import subprocess
import sys
import uuid


def git(*args, check=True):
    result = subprocess.run(['git', *args], text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} falhou: {result.stderr.strip()}")
    return result


def remote_oid(remote, ref):
    result = git('ls-remote', '--exit-code', '--refs', remote, ref, check=False)
    if result.returncode == 2:
        return None
    if result.returncode:
        raise RuntimeError(f'Não foi possível consultar {remote}: {result.stderr.strip()}')
    return result.stdout.split()[0]


def synchronize(action, ref, source, remotes):
    git('check-ref-format', ref)
    if not ref.startswith(('refs/heads/', 'refs/tags/')):
        raise ValueError('Somente branches e tags podem ser sincronizadas.')
    if action == 'delete' and ref == 'refs/heads/main':
        raise ValueError('A main não pode ser removida automaticamente.')
    if action not in ('sync', 'delete'):
        raise ValueError('Ação inválida.')

    target = git('rev-parse', '--verify', source).stdout.strip() if action == 'sync' else None
    snapshots = []
    run_id = uuid.uuid4().hex
    # Antes de escrever, guarda os objetos necessários para restaurar cada remoto.
    for index, remote in enumerate(remotes):
        old = remote_oid(remote, ref)
        if old:
            backup = f'refs/mirror-backup/{run_id}/{index}'
            git('fetch', '--no-tags', remote, f'+{ref}:{backup}')
            saved = git('rev-parse', '--verify', backup).stdout.strip()
            if old != saved:
                raise RuntimeError(f'A referência em {remote} mudou durante a preparação.')
        snapshots.append((remote, old))

    changed = []
    try:
        for remote, old in snapshots:
            origin = remote_oid('origin', ref)
            if action == 'delete' and origin is not None:
                raise RuntimeError('A referência foi recriada no GitHub; exclusão cancelada.')
            if action == 'sync' and origin != target:
                raise RuntimeError('A referência no GitHub mudou após a validação.')
            if remote_oid(remote, ref) != old:
                raise RuntimeError(f'A referência em {remote} mudou após a preparação.')
            if old == target:
                continue
            # Registra a tentativa antes de enviar: uma falha de rede pode ocorrer
            # depois de o servidor ter aplicado a alteração.
            changed.append((remote, old))
            if action == 'delete':
                git('push', f'--force-with-lease={ref}:{old}', remote, f':{ref}')
            else:
                git('push', remote, f'{source}:{ref}')
    except Exception as error:
        failures = []
        for remote, old in reversed(changed):
            try:
                actual = remote_oid(remote, ref)
                if actual == old:
                    continue
                if actual != target:
                    raise RuntimeError('A referência mudou novamente; reversão cancelada para evitar perda de dados.')
                expected = actual or ''
                restore = f'{old}:{ref}' if old else f':{ref}'
                git('push', f'--force-with-lease={ref}:{expected}', remote, restore)
                print(f'Referência restaurada em {remote}')
            except Exception as rollback_error:
                failures.append(f'{remote}: {rollback_error}')
        if failures:
            raise RuntimeError(f'{error}\nREVERSÃO INCOMPLETA: ' + '; '.join(failures)) from error
        raise RuntimeError(f'{error}\nAlterações anteriores revertidas.') from error


if __name__ == '__main__':
    try:
        synchronize(os.environ['MIRROR_ACTION'], os.environ['MIRROR_REF'],
                    os.environ.get('MIRROR_SOURCE', ''),
                    ['git@codeberg.org:markelpher/KookieChan.git', 'git@gitlab.com:markelpher/kookiechan.git'])
    except Exception as exc:
        print(f'Falha na sincronização: {exc}', file=sys.stderr)
        raise SystemExit(1)
