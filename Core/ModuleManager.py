#!/usr/bin/env python3

import contextlib
import os
import shutil
import site
import sys
import venv
import subprocess
import yaml
import pygit2
from pathlib import Path
from enum import Enum
from urllib.parse import urlparse
from uuid import uuid4

from PySide6 import QtWidgets, QtCore


class ModulesManager:

    def __init__(self, mainWindow):
        self.mainWindow = mainWindow
        self.baseAppStoragePath = Path(
            QtCore.QStandardPaths.standardLocations(
                QtCore.QStandardPaths.StandardLocation.AppDataLocation)[0])
        self.baseAppStoragePath.mkdir(exist_ok=True, parents=True)
        self.modulesBaseDirectoryPath = self.baseAppStoragePath / "User Module Packs Storage"
        self.modulesBaseDirectoryPath.mkdir(exist_ok=True)
        self.modulesDirectoryPath = self.modulesBaseDirectoryPath / "Modules"
        self.modulesDirectoryPath.mkdir(exist_ok=True)
        self.modulesPythonPath = self.modulesBaseDirectoryPath / 'bin' / 'python3'
        self.sources = {}
        self.modulePacks = {}
        self.modules = {}

        self.venvThread = InitialiseVenvThread(self)
        self.venvThread.configureVenvOfMainThreadSignal.connect(self.configureVenv)
        self.venvThread.start()

    def save(self) -> bool:
        self.mainWindow.SETTINGS.setValue("Program/Sources/Sources List", self.sources)
        self.mainWindow.SETTINGS.setValue("Program/Sources/Module Packs List", self.modulePacks)
        return True

    def loadYamlFile(self, filePath: Path):
        with open(filePath, 'r') as yamlFile:
            try:
                fileContents = yaml.safe_load(yamlFile)
            except yaml.YAMLError:
                self.mainWindow.MESSAGEHANDLER.error(f'Exception while processing YAML file: {filePath}.')
                return None
        return fileContents

    def configureVenv(self, venvPath):
        binDir = os.path.dirname(venvPath / 'bin')
        base = binDir[: -len("bin") - 1]  # strip away the bin part from the __file__, plus the path separator

        # prepend bin to PATH (this file is inside the bin directory)
        os.environ["PATH"] = os.pathsep.join([binDir] + os.environ.get("PATH", "").split(os.pathsep))
        os.environ["VIRTUAL_ENV"] = base  # virtual env is right above bin directory

        # add the virtual environments libraries to the host python import mechanism
        prevLength = len(sys.path)
        packagesPath = str(list((venvPath / 'lib').glob('python*'))[0] / 'site-packages')

        for lib in packagesPath.split(os.pathsep):
            path = os.path.realpath(os.path.join(binDir, lib))
            site.addsitedir(path)
        sys.path[:] = sys.path[prevLength:] + sys.path[:prevLength]

        sys.real_prefix = sys.prefix
        sys.prefix = base

        self.mainWindow.MESSAGEHANDLER.info("Loaded Modules environment.")
        self.mainWindow.MESSAGEHANDLER.debug(f"OS Path: {os.environ['PATH']}")

    def loadModule(self, uniqueModuleName: str) -> bool:
        newModuleDirectoryPath = self.modulesDirectoryPath / uniqueModuleName
        moduleDetailsPath = newModuleDirectoryPath / "module.yml"
        if not moduleDetailsPath.exists():
            moduleDetailsPath = newModuleDirectoryPath / "module.yaml"
            if not moduleDetailsPath.exists():
                self.mainWindow.MESSAGEHANDLER.error(f'Could not load Module {uniqueModuleName}: '
                                                     f'module.yml not found.')
            return False

        if not (moduleDetails := self.loadYamlFile(moduleDetailsPath)):
            return False

        try:
            author = moduleDetails['Author']
            version = moduleDetails['Version']
            moduleName = moduleDetails['Module Name']
            notes = moduleDetails['Notes']
        except Exception as exc:
            self.mainWindow.MESSAGEHANDLER.error(f'Could not load Module {uniqueModuleName}. '
                                                 f'Exception while loading module details: {exc}')
            return False

        moduleEntities = self.mainWindow.RESOURCEHANDLER.loadModuleEntities(
            newModuleDirectoryPath / "Entities")
        moduleResolutions = self.mainWindow.RESOLUTIONMANAGER.loadResolutionsFromDir(
            newModuleDirectoryPath / "Resolutions")
        self.modules[uniqueModuleName] = {'author': author, 'version': version, 'name': moduleName, 'notes': notes,
                                          'entities': moduleEntities, 'resolutions': moduleResolutions}
        self.mainWindow.MESSAGEHANDLER.info(f'Loaded Module: {moduleName}')
        return True

    def loadAllModules(self) -> bool:
        moduleLoadFailuresCount = 0
        for uniqueModuleName in os.listdir(self.modulesDirectoryPath):
            if not self.loadModule(uniqueModuleName):
                moduleLoadFailuresCount += 1
                if moduleLoadFailuresCount > 2:
                    self.mainWindow.MESSAGEHANDLER.critical(
                        'Failed loading too many Modules, aborting Module loading.',
                        exc_info=False,
                    )
                    return False
            self.mainWindow.MESSAGEHANDLER.info(f'Loaded module: {uniqueModuleName}')
        return True

    def showSourcesManager(self):
        SourcesManager(self).exec()

    def installSource(self, newSourceDict: dict) -> bool:
        newSourceURI = newSourceDict['URI']

        authType = AuthType.NONE
        authCreds = None
        schemaType = SchemaType.LOCAL
        if isRemote := newSourceDict['Remote']:
            authDetails = newSourceDict['Auth']
            parsedURL = urlparse(newSourceURI)
            if authDetails is not None:
                username = authDetails[0]
                passAuth = authDetails[1]
                authType = AuthType.KEY if isinstance(authDetails[1], Path) else AuthType.PASSWORD
                authCreds = (username, passAuth)

            # Scheme does not matter for now because we always assume that we are pointed to a repository.
            #   This might change in the future. 10/05/2023
            if parsedURL.scheme in ['https', 'http']:
                schemaType = schemaType.HTTPS
            elif parsedURL.scheme == 'ssh':
                schemaType = schemaType.SSH
            elif parsedURL.scheme == 'git':
                schemaType = schemaType.GIT
            else:
                self.mainWindow.MESSAGEHANDLER.error(f'Cannot add source: {newSourceURI}\n\n'
                                                     f'Reason: Unsupported Schema type: {parsedURL.scheme}.',
                                                     popUp=True,
                                                     exc_info=False)
                return False
        elif newSourceURI.lower().startswith('file://'):
            newSourceURI = newSourceURI[7:]

        if newSourceURI in self.sources:
            self.mainWindow.MESSAGEHANDLER.error(f'Cannot add source: {newSourceURI}\n\n'
                                                 f'Reason: Source already exists.',
                                                 popUp=True,
                                                 exc_info=False)
            return False

        self.sources[newSourceURI] = {'URI': newSourceURI, 'Remote': isRemote, 'AuthType': authType,
                                      'AuthCreds': authCreds, 'SchemaType': schemaType, 'UUID': str(uuid4())}
        if self.syncSource(newSourceURI):
            self.save()
        else:
            self.sources.pop(newSourceURI)
            return False

        return True

    def uninstallSource(self, sourceURI: str) -> bool:
        source = self.sources.pop(sourceURI)
        shutil.rmtree(self.modulesBaseDirectoryPath / source['UUID'])
        self.save()
        return True

    def syncSource(self, sourceURI: str) -> bool:
        source = self.sources[sourceURI]
        sourceUUID = source['UUID']
        destinationPath = self.modulesBaseDirectoryPath / sourceUUID

        if source['Remote']:
            if authType := source['AuthType']:
                authCreds = source['AuthCreds']
                if authType == AuthType.PASSWORD:
                    callbacks = pygit2.RemoteCallbacks(credentials=pygit2.UserPass(username=authCreds[0],
                                                                                   password=authCreds[1]))
                else:
                    callbacks = pygit2.RemoteCallbacks(credentials=pygit2.Keypair(username=authCreds[0],
                                                                                  privkey=authCreds[1],
                                                                                  pubkey=authCreds[2],
                                                                                  passphrase=""))
                pygit2.clone_repository(source['URI'], destinationPath, callbacks=callbacks)
            else:
                pygit2.clone_repository(source['URI'], destinationPath)
        else:
            shutil.copytree(Path(sourceURI), destinationPath, dirs_exist_ok=True)

        if not (modulePackFiles := [file for file in os.listdir(destinationPath) if file.endswith(('.yml', '.yaml'))]):
            self.mainWindow.MESSAGEHANDLER.error(f'No Module Pack files found for source: {sourceURI}.',
                                                 popUp=True,
                                                 exc_info=False)
            return False

        if sourceUUID not in self.modulePacks:
            self.modulePacks[sourceUUID] = []

        for modulePack in modulePackFiles:
            modulePackPath = destinationPath / modulePack
            if not (packDetails := self.loadYamlFile(modulePackPath)):
                continue
            packDetails['UUID'] = str(uuid4())
            self.modulePacks[sourceUUID].append(packDetails)

        return True

    def installModule(self, uniqueModuleName: str, moduleFilePath: Path) -> bool:
        newModuleDirectoryPath = self.modulesDirectoryPath / uniqueModuleName
        if newModuleDirectoryPath.exists():
            self.mainWindow.MESSAGEHANDLER.error(f'Could not install Module {uniqueModuleName}: Module already exists.',
                                                 popUp=True, exc_info=False)
            return False
        shutil.copytree(moduleFilePath, newModuleDirectoryPath, dirs_exist_ok=True)

        moduleRequirements = newModuleDirectoryPath / "requirements.txt"
        moduleAssetsPath = newModuleDirectoryPath / "assets"
        resolutionsPath = newModuleDirectoryPath / "Resolutions"
        entitiesPath = newModuleDirectoryPath / "Entities"
        moduleAssetsPath.mkdir(exist_ok=True)
        resolutionsPath.mkdir(exist_ok=True)
        entitiesPath.mkdir(exist_ok=True)

        moduleDetailsPath = newModuleDirectoryPath / "module.yml"
        if not moduleDetailsPath.exists():
            moduleDetailsPath = newModuleDirectoryPath / "module.yaml"
            if not moduleDetailsPath.exists():
                self.mainWindow.MESSAGEHANDLER.error(f'Could not install Module {uniqueModuleName}: '
                                                     f'module.yml not found.')
            shutil.rmtree(newModuleDirectoryPath)
            return False

        if not (moduleDetails := self.loadYamlFile(moduleDetailsPath)):
            shutil.rmtree(newModuleDirectoryPath)
            return False

        try:
            author = moduleDetails['Author']
            version = moduleDetails['Version']
            moduleName = moduleDetails['Module Name']
            notes = moduleDetails['Notes']
        except Exception as exc:
            self.mainWindow.MESSAGEHANDLER.error(f'Could not install Module {uniqueModuleName}. '
                                                 f'Exception while loading module details: {exc}')
            shutil.rmtree(newModuleDirectoryPath)
            return False

        if moduleRequirements.exists():
            cmdStr = f"'{self.modulesPythonPath}' -m pip install -r '{moduleRequirements}'"
            subprocess.run(cmdStr, shell=True)

        self.mainWindow.MESSAGEHANDLER.info(f'Loaded module {moduleName} version {version} by {author}.')
        self.mainWindow.MESSAGEHANDLER.debug(f'Module {moduleName} notes: {notes}')
        return True

    def uninstallModule(self, uniqueModuleName: str) -> bool:
        newModuleDirectoryPath = self.modulesDirectoryPath / uniqueModuleName
        if not newModuleDirectoryPath.exists():
            self.mainWindow.MESSAGEHANDLER.error(f'Could not uninstall Module {uniqueModuleName}: '
                                                 f'Module does not exist.')
            self.modules.pop(uniqueModuleName)
            return False
        try:
            shutil.rmtree(newModuleDirectoryPath)
        except Exception as exc:
            self.mainWindow.MESSAGEHANDLER.error(f'Could not uninstall Module {uniqueModuleName}: '
                                                 f'Error occurred: {exc}.')
            return False

        # No need to uninstall anything from venv - more likely to cause issues than fix anything.
        self.modules.pop(uniqueModuleName)
        return True


class SourcesManager(QtWidgets.QDialog):

    def __init__(self, modulesManager: ModulesManager):
        super().__init__()
        self.modulesManager = modulesManager
        self.setWindowTitle('Sources Manager')

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        sourcesListLabel = QtWidgets.QLabel('Installed Sources')
        sourcesListLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.sourcesList = QtWidgets.QListWidget()
        self.sourcesList.setLayoutMode(self.sourcesList.LayoutMode.SinglePass)
        self.sourcesList.setSelectionMode(self.sourcesList.SelectionMode.SingleSelection)
        for source in self.modulesManager.sources:
            self.sourcesList.addItem(source)

        addSourceButton = QtWidgets.QPushButton('Add New Source')
        addSourceButton.clicked.connect(self.addSource)
        removeSourceButton = QtWidgets.QPushButton('Remove Selected Source')
        removeSourceButton.clicked.connect(self.removeSource)

        layout.addWidget(sourcesListLabel, 0, 0, 1, 2)
        layout.addWidget(self.sourcesList, 1, 0, 3, 2)
        layout.addWidget(addSourceButton, 4, 1, 1, 1)
        layout.addWidget(removeSourceButton, 4, 0, 1, 1)

    def addSource(self) -> bool:
        addSourceDialog = AddSourceDialog()
        if addSourceDialog.exec():
            newSource = addSourceDialog.sourceDict
            newSourceURI = newSource['URI']
            if self.modulesManager.installSource(newSource):
                self.sourcesList.addItem(newSourceURI)
                return True
            return False

    def removeSource(self) -> bool:
        with contextlib.suppress(IndexError):
            selectedItem = self.sourcesList.selectedItems()[0]
            if self.modulesManager.uninstallSource(selectedItem.text()):
                self.sourcesList.takeItem(self.sourcesList.row(selectedItem))
                return True
            return False


class AddSourceDialog(QtWidgets.QDialog):

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)
        self.setWindowTitle('Add New Source')

        addSourceLabel = QtWidgets.QLabel('Fill in the fields to add a new source.\n'
                                          'Sources must either be a folder on the local system, or a remote Git '
                                          'repository, accessible via the HTTP, SSH or GIT transports.\n'
                                          'Examples:\nLocal URI:\n\t/home/user/source_folder\nRemote URI:\n\t'
                                          'git://github.com/example/example.git')
        addSourceLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        localOrRemoteSource = QtWidgets.QWidget()
        localOrRemoteSourceLayout = QtWidgets.QVBoxLayout()
        localOrRemoteSource.setLayout(localOrRemoteSourceLayout)
        self.localSourceRadioButton = QtWidgets.QRadioButton('Local Source', localOrRemoteSource)
        self.remoteSourceRadioButton = QtWidgets.QRadioButton('Remote Source', localOrRemoteSource)
        self.remoteSourceRadioButton.setChecked(True)
        self.remoteSourceRadioButton.toggled.connect(self.toggleLocalOrRemote)
        localOrRemoteSourceLayout.addWidget(self.localSourceRadioButton)
        localOrRemoteSourceLayout.addWidget(self.remoteSourceRadioButton)

        localOrRemoteInput = QtWidgets.QWidget()
        self.localOrRemoteInputLayout = QtWidgets.QStackedLayout()
        localOrRemoteInput.setLayout(self.localOrRemoteInputLayout)

        remoteInputContainerWidget = QtWidgets.QWidget()
        remoteInputContainerWidgetLayout = QtWidgets.QGridLayout()
        remoteInputContainerWidget.setLayout(remoteInputContainerWidgetLayout)
        remoteInputLabel = QtWidgets.QLabel('Enter the URI of the new source:')
        remoteInputLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        remoteInputContainerWidgetLayout.addWidget(remoteInputLabel, 0, 0)
        self.remoteSourceInput = QtWidgets.QLineEdit()
        remoteInputContainerWidgetLayout.addWidget(self.remoteSourceInput, 1, 0)

        self.localOrRemoteInputLayout.addWidget(remoteInputContainerWidget)

        localInputContainerWidget = QtWidgets.QWidget()
        localInputContainerWidgetLayout = QtWidgets.QGridLayout()
        localInputContainerWidget.setLayout(localInputContainerWidgetLayout)
        localInputLabel = QtWidgets.QLabel('Enter the path to the new source:')
        localInputLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        localInputContainerWidgetLayout.addWidget(localInputLabel, 0, 0, 1, 2)
        self.localSourceInput = QtWidgets.QLineEdit()
        self.localSourceInput.setToolTip('Input the local path to the folder containing the module packs.')
        localInputContainerWidgetLayout.addWidget(self.localSourceInput, 1, 0, 1, 1)
        localInputSelectFileButton = QtWidgets.QPushButton('Select Folder')
        localInputSelectFileButton.clicked.connect(self.selectLocalSourceFolder)
        localInputContainerWidgetLayout.addWidget(localInputSelectFileButton, 1, 1, 1, 1)

        self.localOrRemoteInputLayout.addWidget(localInputContainerWidget)

        authenticationLabel = QtWidgets.QLabel('Specify the Authentication needed to access the source:')
        authenticationLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.authenticationOptionWidget = QtWidgets.QWidget()
        authenticationOptionWidgetLayout = QtWidgets.QVBoxLayout()
        self.authenticationOptionWidget.setLayout(authenticationOptionWidgetLayout)
        self.noAuthentication = QtWidgets.QRadioButton('No Authentication', self.authenticationOptionWidget)
        self.noAuthentication.clicked.connect(lambda: self.toggleAuthCreds(0))
        self.usernameAndPassword = QtWidgets.QRadioButton('Username and Password', self.authenticationOptionWidget)
        self.usernameAndPassword.clicked.connect(lambda: self.toggleAuthCreds(1))
        self.usernameAndKey = QtWidgets.QRadioButton('Username and Key File', self.authenticationOptionWidget)
        self.usernameAndKey.clicked.connect(lambda: self.toggleAuthCreds(2))
        self.noAuthentication.setChecked(True)
        authenticationOptionWidgetLayout.addWidget(self.noAuthentication)
        authenticationOptionWidgetLayout.addWidget(self.usernameAndPassword)
        authenticationOptionWidgetLayout.addWidget(self.usernameAndKey)

        self.authenticationCredentialsWidget = QtWidgets.QWidget()
        self.authenticationCredentialsWidgetLayout = QtWidgets.QStackedLayout()
        self.authenticationCredentialsWidget.setLayout(self.authenticationCredentialsWidgetLayout)

        noAuthLabel = QtWidgets.QLabel('No Credentials')
        noAuthLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        usernameAndPasswordWidget = QtWidgets.QWidget()
        usernameAndPasswordWidgetLayout = QtWidgets.QFormLayout()
        usernameAndPasswordWidget.setLayout(usernameAndPasswordWidgetLayout)
        self.usernameInputField = QtWidgets.QLineEdit()
        self.passwordInputField = QtWidgets.QLineEdit()
        usernameAndPasswordWidgetLayout.addRow('Username:', self.usernameInputField)
        usernameAndPasswordWidgetLayout.addRow('Password:', self.passwordInputField)

        usernameAndKeyWidget = QtWidgets.QWidget()
        usernameAndKeyWidgetLayout = QtWidgets.QGridLayout()
        usernameAndKeyWidget.setLayout(usernameAndKeyWidgetLayout)
        privateKeyFileLineWidget = QtWidgets.QWidget()
        privateKeyFileLineWidgetLayout = QtWidgets.QHBoxLayout()
        privateKeyFileLineWidget.setLayout(privateKeyFileLineWidgetLayout)
        publicKeyFileLineWidget = QtWidgets.QWidget()
        publicKeyFileLineWidgetLayout = QtWidgets.QHBoxLayout()
        publicKeyFileLineWidget.setLayout(publicKeyFileLineWidgetLayout)
        self.keyUsernameInputField = QtWidgets.QLineEdit()
        self.privateKeyInputField = QtWidgets.QLineEdit()
        self.publicKeyInputField = QtWidgets.QLineEdit()
        privateKeyInputButton = QtWidgets.QPushButton('Select File')
        privateKeyInputButton.clicked.connect(self.selectLocalPrivateKeyFile)
        publicKeyInputButton = QtWidgets.QPushButton('Select File')
        publicKeyInputButton.clicked.connect(self.selectLocalPublicKeyFile)
        privateKeyFileLineWidgetLayout.addWidget(self.privateKeyInputField)
        privateKeyFileLineWidgetLayout.addWidget(privateKeyInputButton)
        publicKeyFileLineWidgetLayout.addWidget(self.publicKeyInputField)
        publicKeyFileLineWidgetLayout.addWidget(publicKeyInputButton)
        usernameAndKeyWidgetLayout.addWidget(QtWidgets.QLabel('Username:'), 0, 0, 1, 1)
        usernameAndKeyWidgetLayout.addWidget(self.keyUsernameInputField, 0, 1, 1, 1)
        usernameAndKeyWidgetLayout.addWidget(QtWidgets.QLabel('Private Key File:'), 1, 0, 1, 1)
        usernameAndKeyWidgetLayout.addWidget(privateKeyFileLineWidget, 1, 1, 1, 1)
        usernameAndKeyWidgetLayout.addWidget(QtWidgets.QLabel('Public Key File:'), 2, 0, 1, 1)
        usernameAndKeyWidgetLayout.addWidget(publicKeyFileLineWidget, 2, 1, 1, 1)

        self.authenticationCredentialsWidgetLayout.addWidget(noAuthLabel)
        self.authenticationCredentialsWidgetLayout.addWidget(usernameAndPasswordWidget)
        self.authenticationCredentialsWidgetLayout.addWidget(usernameAndKeyWidget)

        cancelButton = QtWidgets.QPushButton('Cancel')
        cancelButton.clicked.connect(self.reject)
        confirmButton = QtWidgets.QPushButton('Confirm')
        confirmButton.clicked.connect(self.accept)

        layout.addWidget(addSourceLabel, 0, 0, 1, 2)
        layout.addWidget(localOrRemoteSource, 1, 0, 1, 2)
        layout.addWidget(localOrRemoteInput, 2, 0, 1, 2)
        layout.addWidget(self.authenticationOptionWidget, 3, 0, 2, 2)
        layout.addWidget(self.authenticationCredentialsWidget, 5, 0, 2, 2)
        layout.addWidget(cancelButton, 7, 0, 1, 1)
        layout.addWidget(confirmButton, 7, 1, 1, 1)

        self.sourceDict = {}

    def toggleAuthCreds(self, credsOption: int) -> None:
        self.authenticationCredentialsWidgetLayout.setCurrentIndex(credsOption)

    def toggleLocalOrRemote(self) -> None:
        if self.remoteSourceRadioButton.isChecked():
            self.localOrRemoteInputLayout.setCurrentIndex(0)
            self.authenticationOptionWidget.setDisabled(False)
            self.authenticationCredentialsWidget.setDisabled(False)
        else:
            self.authenticationOptionWidget.setDisabled(True)
            self.authenticationCredentialsWidget.setDisabled(True)
            self.noAuthentication.setChecked(True)
            self.localOrRemoteInputLayout.setCurrentIndex(1)
            self.authenticationCredentialsWidgetLayout.setCurrentIndex(0)

    def selectLocalSourceFolder(self) -> None:
        sourceFolderDialog = QtWidgets.QFileDialog()
        sourceFolderDialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        sourceFolderDialog.setViewMode(QtWidgets.QFileDialog.ViewMode.List)
        sourceFolderDialog.setFileMode(QtWidgets.QFileDialog.FileMode.Directory)
        sourceFolderDialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        sourceFolderDialog.setDirectory(str(Path.home()))

        if sourceFolderDialog.exec():
            folderPath = Path(sourceFolderDialog.selectedFiles()[0])
            if folderPath.exists():
                self.localSourceInput.setText(str(folderPath))

    def selectLocalPrivateKeyFile(self) -> None:
        keyFileDialog = QtWidgets.QFileDialog()
        keyFileDialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        keyFileDialog.setViewMode(QtWidgets.QFileDialog.ViewMode.List)
        keyFileDialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        keyFileDialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        keyFileDialog.setDirectory(str(Path.home()))

        if keyFileDialog.exec():
            filePath = Path(keyFileDialog.selectedFiles()[0])
            if filePath.exists():
                self.privateKeyInputField.setText(str(filePath))

    def selectLocalPublicKeyFile(self) -> None:
        keyFileDialog = QtWidgets.QFileDialog()
        keyFileDialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        keyFileDialog.setViewMode(QtWidgets.QFileDialog.ViewMode.List)
        keyFileDialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        keyFileDialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        keyFileDialog.setDirectory(str(Path.home()))

        if keyFileDialog.exec():
            filePath = Path(keyFileDialog.selectedFiles()[0])
            if filePath.exists():
                self.publicKeyInputField.setText(str(filePath))

    def accept(self) -> None:
        self.sourceDict['Remote'] = not self.localSourceRadioButton.isChecked()
        if self.noAuthentication.isChecked():
            self.sourceDict['Auth'] = None
        elif self.usernameAndPassword.isChecked():
            self.sourceDict['Auth'] = (self.usernameInputField.text(), self.passwordInputField.text())
        else:
            self.sourceDict['Auth'] = (self.keyUsernameInputField.text(),
                                       Path(self.privateKeyInputField.text()),
                                       Path(self.publicKeyInputField.text()))
        self.sourceDict['URI'] = self.remoteSourceInput.text() \
            if self.sourceDict['Remote'] else self.localSourceInput.text()
        super().accept()


class ModulePacksListViewer(QtWidgets.QDialog):

    def __init__(self, parent: ModulesManager):
        super().__init__()
        self.modulesManager = parent

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        self.setWindowTitle('Installed Modules List')

        installedModulesLabel = QtWidgets.QLabel("Installed Modules")
        layout.addWidget(installedModulesLabel)

        self.modulePackList = QtWidgets.QListWidget()
        addModulePackButton = QtWidgets.QPushButton('+')
        removeModulePackButton = QtWidgets.QPushButton('-')

        closeButton = QtWidgets.QPushButton('Close')
        closeButton.clicked.connect(self.accept)

    def removeModulePack(self) -> bool:
        itemsToRemove = self.modulePackList.selectedItems()
        if len(itemsToRemove) < 1:
            self.modulesManager.mainWindow.MESSAGEHANDLER.warning('No items selected, nothing to remove.', popUp=True)
            return True
        for item in itemsToRemove:
            pass

    def addModulePack(self) -> bool:
        if addModuleDialog := AddModuleDialog().exec():
            print('RET', addModuleDialog)
            # TODO
            return True
        return False


class ModuleDetailsViewer(QtWidgets.QDialog):

    def __init__(self, moduleDetails: dict):
        super().__init__()
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        self.setWindowTitle(f'Details for Module: {moduleDetails["name"]}')
        authorLabel = QtWidgets.QLabel('Author:')
        authorText = QtWidgets.QLineEdit(moduleDetails['author'])
        authorText.setReadOnly(True)
        versionLabel = QtWidgets.QLabel('Version:')
        versionText = QtWidgets.QLineEdit(moduleDetails['version'])
        versionText.setReadOnly(True)
        nameLabel = QtWidgets.QLabel('Notes:')
        nameText = QtWidgets.QTextEdit(moduleDetails['notes'])
        nameText.setReadOnly(True)
        entitiesLabel = QtWidgets.QLabel('Entities:')
        resolutionsLabel = QtWidgets.QLabel('Resolutions:')


class AddModuleDialog(QtWidgets.QDialog):

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        self.setWindowTitle('Add Module')
        self.moduleToAddPath = QtWidgets.QLineEdit()
        instructionText = QtWidgets.QLabel('Enter the path to the folder containing the module to install, or '
                                           'the URL to a git repository where the module is stored.')
        instructionText.setWordWrap(True)
        instructionText.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.moduleToAddPath.setPlaceholderText('Path to new Module')
        self.moduleToAddPath.setToolTip('Either paste a URL from a site like Github, or a path to a local folder.')
        selectLocalFolderButton = QtWidgets.QPushButton('Select Local Folder')
        selectLocalFolderButton.clicked.connect(self.selectLocalFolder)
        acceptButton = QtWidgets.QPushButton('Confirm')
        acceptButton.clicked.connect(self.accept)
        rejectButton = QtWidgets.QPushButton('Cancel')
        rejectButton.clicked.connect(self.reject)

    def selectLocalFolder(self) -> None:
        moduleFolderDialog = QtWidgets.QFileDialog()
        moduleFolderDialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        moduleFolderDialog.setViewMode(QtWidgets.QFileDialog.ViewMode.List)
        moduleFolderDialog.setFileMode(QtWidgets.QFileDialog.FileMode.Directory)
        moduleFolderDialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        moduleFolderDialog.setDirectory(str(Path.home()))

        if moduleFolderDialog.exec():
            folderPath = Path(moduleFolderDialog.selectedFiles()[0])
            self.moduleToAddPath.setText(str(folderPath))

    def accept(self) -> None:
        moduleLoc = self.moduleToAddPath.text()
        pass  # TODO - Check for validity
        if moduleLoc:  # Check if URL
            pass
        else:
            moduleLocPath = Path(moduleLoc)
        super().accept()


class InitialiseVenvThread(QtCore.QThread):
    configureVenvOfMainThreadSignal = QtCore.Signal(Path)

    def __init__(self, modulesManager: ModulesManager) -> None:
        super().__init__()
        self.modulesManager = modulesManager

    def run(self) -> None:
        venvPath = self.modulesManager.modulesBaseDirectoryPath
        if not (venvPath / 'bin').exists():
            venv.create(venvPath, symlinks=True, with_pip=True, upgrade_deps=True)

        self.configureVenvOfMainThreadSignal.emit(venvPath)

        # Install / upgrade playwright & misc if not already installed, since they need special treatment.
        cmdStr = f"'{self.modulesManager.modulesPythonPath}' -m pip install --upgrade wheel setuptools playwright && " \
                 f"'{self.modulesManager.modulesPythonPath}' -m playwright install"
        subprocess.run(cmdStr, shell=True)


class AuthType(Enum):
    NONE = 0
    PASSWORD = 1
    KEY = 2


class SchemaType(Enum):
    LOCAL = 0
    HTTPS = 1
    SSH = 2
    GIT = 3