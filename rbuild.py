#!/bin/env python3

import argparse
import hashlib
import json
import subprocess
import tempfile
import os
import sys
from datetime import datetime
from typing import (
	List,
	Dict,
	Any,
	Optional,
	Set,
	Tuple
)

# Constants for labels
CONFIG_HASH_LABEL = 'rbuild.config_sha256'
BUILD_TIME_LABEL = 'rbuild.build_time'
COMPOSE_NAME_LABEL = 'rbuild.compose_name'

def parse_env_var_to_int(key: str, default: Optional[int] = None) -> int:
	"""Parses an environment variable to an integer value."""
	try:
		timeout = os.getenv(key, default=default)
		return int(timeout)
	except (ValueError, TypeError):
		raise ValueError(f'Failed to parse "{key}", should be a numeric time in seconds')

def die(*kargs, exit_status : int = 1, **kwargs):
	"""Kill the program with a custom message"""
	print(*kargs, **kwargs, file=sys.stderr)
	sys.exit(exit_status)

def run_command(command: List[str]) -> str:
	"""Runs a command and returns the stdout."""

	command_str = ' '.join(command)
	try:
		result = subprocess.run(command, stdout=subprocess.PIPE, text=True, check=True)
	except subprocess.CalledProcessError as e:
		die(f'Failed to run command: "{command_str}", exited={e.returncode}')
	except subprocess.TimeoutExpired:
		die(f'Command timed out: "{command_str}"')
	return result.stdout

def is_image_expired(image: str, config_sha256: str, build_ttl: int) -> bool:
	"""Checks if a docker image is expired."""
	inspect_output = run_command(['docker', 'inspect', image])
	labels = json.loads(inspect_output)[0]['Config']['Labels']

	if labels.get('rbuild.config_sha256') != config_sha256:
		return True

	build_time = datetime.fromisoformat(labels.get('rbuild.build_time'))
	delta = datetime.utcnow() - build_time

	return delta.total_seconds() > build_ttl

def remove_images(compose_name : str, operating_images : Set[str] = set()):
	""" Remove images created by rbuild, provided operating_images it purges stale images"""
	stale_images = []

	image_list_output = run_command(['docker', 'image', 'list', '--format', 'json'])
	for image_output in image_list_output.split('\n'):

		if not image_output:
			continue

		img = json.loads(image_output)

		image_inspect_output = run_command(['docker', 'inspect', img['ID']])

		image_details = json.loads(image_inspect_output)[0]

		labels = image_details['Config']['Labels']

		image_name = labels.get('rbuild.compose_name') if labels else None

		if image_name != compose_name or \
			any((tag in operating_images for tag in image_details['RepoTags'])):
			continue

		stale_images.append(img['ID'])

	if stale_images:
		run_command(['docker', 'image', 'rm', *stale_images])

def read_config(filename : str) -> Tuple[str, Dict]:
	""" Read the config from disk """

	config_output = run_command(['docker', 'compose', '-f', filename, 'config', '--format', 'json'])

	config = json.loads(config_output)

	return config_output, config

def build_main(filename: str, force_rebuild=False) -> None:
	config_output, config = read_config(filename)

	config_sha256 = hashlib.sha256(config_output.encode()).hexdigest()

	name = config.get('name')

	# 2. Determine if working images are expired
	ps_output = run_command(['docker', 'compose', '-f', filename, 'ps', '--all', '--format', 'json'])
	containers = json.loads(ps_output)

	any_expired = False

	for container in containers:
		image = container.get('Image')
		if is_image_expired(image, config_sha256, BUILD_TTL):
			any_expired = True
			break

	if not (force_rebuild or any_expired or len(containers) == 0):
		exit(0)

	# 3. Modify config
	build_time = datetime.utcnow()
	operating_images = set()
	for service_name, service_data in config['services'].items():
		labels = service_data.setdefault('build', {}).setdefault('labels', {})

		labels['rbuild.config_sha256'] = config_sha256
		labels['rbuild.build_time'] = build_time.isoformat()
		labels['rbuild.compose_name'] = name

		new_image = f'rbuild-{name}-{service_name}:{build_time.timestamp()}'
		operating_images.add(new_image)
		service_data['image'] = new_image

	# 4. Save this config to a temporary JSON file
	with tempfile.NamedTemporaryFile(mode='w+', suffix='.json') as temp_file:
		json.dump(config, temp_file)

		temp_file.flush()

		# 5. Build and bring the dockerfile up
		subprocess.run(['docker', 'compose', '-f', temp_file.name, 'build', '--no-cache', '--pull'], check=True)
		subprocess.run([
			'docker', 'compose', '-f', temp_file.name,
			'up', '--remove-orphans', '--detach', f'--wait-timeout={UP_TIMEOUT_PERIOD}'
		], check=True)

	# 6. Get rid of stale images
	remove_images(name, operating_images)

def remove_main(filename : str) -> None:
	""" Remove all images """

	_, config = read_config(filename)
	compose_name = config['name']
	remove_images(compose_name)
	sys.exit(0)

if __name__ == '__main__':
	BUILD_TTL = parse_env_var_to_int('BUILD_TTL', default=(24 * 60 * 60))
	UP_TIMEOUT_PERIOD = parse_env_var_to_int('UP_TIMEOUT_PERIOD', default=60)

	parser = argparse.ArgumentParser(description='Automatically rebuild a series of containers with docker compose.')

	parser.add_argument('filename', type=str, nargs='+', help='The docker-compose file to use.')

	parser.add_argument('--build-period', type=int, default=BUILD_TTL, help='Time images are allowed to live (in seconds.)')
	parser.add_argument('--up-timeout-period', type=int, default=UP_TIMEOUT_PERIOD, help='Up timeout period in seconds.')
	parser.add_argument('--force-rebuild', default=False, action='store_true', help='Force all containers to be rebuilt')
	parser.add_argument('--prune-image-cache', default=False, action='store_true', help='Prune the global image cache')

	# Add remove-images to the mutually exclusive group
	parser.add_argument('--remove-images', default=False, action='store_true', help='Remove all images')

	try:
		import argcomplete
		argcomplete.autocomplete(parser)
	except ImportError:
		pass

	args = parser.parse_args()

	# Check for mutual exclusivity
	if args.remove_images and args.force_rebuild:
		die("Error: --remove-images cannot be used with --force-rebuild")

	for filename in args.filename:

		if args.remove_images:
			remove_main(filename)

		build_main(
			filename,
			force_rebuild=args.force_rebuild,
		)

	# Prune the image build cache if requested. The image build cache can gobble
	# up system disk space. A better implementation may create an isolated
	# buildkit instance, ideally providing rbuild a separate cache. The
	# documentation for buildkit instances are fairly sparse and I may add this
	# in the future.
	if args.prune_image_cache:
		subprocess.run([
			"docker", "buildx", "prune", "--force"
		], check=True)

