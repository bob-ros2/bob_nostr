cmake_minimum_required(VERSION 3.10)
project(bob_nostr)

find_package(ament_cmake REQUIRED)

ament_python_install_package(bob_nostr
  SETUP_CFG
    bob_nostr/setup.cfg
  SCRIPTS_DESTINATION
    lib/${PROJECT_NAME}
)

# Install data files
install(
  DIRECTORY launch config skills prompts
  DESTINATION share/${PROJECT_NAME}
)

# Install meta-data
install(
  FILES package.xml
  DESTINATION share/${PROJECT_NAME}
)

# Linting and testing
if(BUILD_TESTING)
  find_package(ament_cmake_copyright REQUIRED)
  ament_copyright(bob_nostr skills tests)

  find_package(ament_cmake_flake8 REQUIRED)
  ament_flake8(bob_nostr skills tests)

  find_package(ament_cmake_pep257 REQUIRED)
  ament_pep257(bob_nostr skills tests)
endif()

ament_package()
