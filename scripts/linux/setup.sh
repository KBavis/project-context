#!/bin/bash


##########
# GLOBALS
##########

# determine if this script is being ran on WSL or native Linux
if grep "microsoft" /proc/version > /dev/null 2>&1; then
	IS_WSL=true
else
	IS_WSL=false 
fi

# find `contextualized` repository home 
PROJECT_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
printf "Contextualized Repository root: $PROJECT_HOME\n\n"




#############
# FUNCTIONS
############

get_available_space() {
	if [ "$IS_WSL" = true ]; then
		echo "WSL Detetected: Checking C:/ Drive for Storage Availability"
		CURRENT_AVAILABLE=$(df -BG /mnt/c | awk 'NR==2 {print $4}' | sed 's/G//')
	else
		echo "Native Linux Detected: Checking Root Drive for Storage Availability"
		CURRENT_AVAILABLE=$(df -BG / | awk 'NR==2 {print $4}' | sed 's/G//')
	fi
}

start_docker() {
	if [ "$IS_WSL" = true ]; then
		echo "WSL Detetected: Enabling Docker via Docker Desktop"
		powershell.exe -Command "Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'"
	else
		echo "Native Linux Detected: Enabling Docker via Systemctl"
		sudo systemctl start docker 
	fi
}

###############
# SCRIPT START
###############



# 1. Ensure that `docker` is available on current machine 
if ! docker info > /dev/null 2>&1; then

	printf "Docker is not running. Attempting to start Docker Desktop..."

	# 2a) Attempt to start Docker 
	start_docker
	

	# 2b) Attempt to validate Docker started
	RETRY_COUNT=0
	while [ $RETRY_COUNT -lt 3 ]; do
		printf "Waiting for Docker to initialize... Attempt $((RETRY_COUNT + 1))/3\n"
		sleep 5 

		if docker info > /dev/null 2>&1; then 
			break
		fi
			((RETRY_COUNT++))
	done
fi

# 1a) Validate Docker setup completed 
if ! docker info > /dev/null 2>&1; then
	printf "\nError: Docker failed to initalize. Please ensure Docker is installed"
	exit 1
fi 

printf "Docker Running: $(docker --version)\n\n"


# 2) Ensure available space required for building Docker Images
MIN_SPACE_REQUIRED=15
echo "Validating ${MIN_SPACE_REQUIRED} GB's available for Docker Images"


# 2a) Determine which drive to search for space availability based on OS 
get_available_space 


# 2b) Ensure that required space is available 
if [ $CURRENT_AVAILABLE -lt $MIN_SPACE_REQUIRED ]; then
	printf "Only ${CURRENT_AVAILABLE}GB's Available; Attempting to prune Docker Images\n"
	
	# attempt to prune 
	docker system prune -f
	
	# re-calculate available space 
	get_available_space

	# final check 
	if [ $CURRENT_AVAILABLE -lt $MIN_SPACE_REQUIRED ]; then
		printf "\nError: Still insufficient space (${CURRENT_AVAILABLE}GBs) after pruning.\n"
		printf "Please manually free up space on host machine and try again.\n"
		exit 1
	else
		printf "Docker pruning successful; necessary space recovered"
	fi
fi

printf "Successfully validated ${CURRENT_AVAILABLE}GB's available\n\n"


# 3) Build Docker Images 
printf "Building Docker Images for Contextualized\n"

# 3a) Frontend
printf "Building Frontend Docker Image...\n"
(
	cd "${PROJECT_HOME}/apps/frontend" || exit 1
	docker build -t frontend-app -f docker/Dockerfile app/ 
)


# 3b)Backend
printf "\nBuilding Backend Docker Image...\n"
(
	cd "${PROJECT_HOME}/apps/backend"
	docker build -t backend-app -f docker/Dockerfile .
)

printf "Successfully build backend and frontend docker images\n\n"







