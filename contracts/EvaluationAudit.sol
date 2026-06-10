// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract FacultyEvaluation {
    struct EvaluationRecord {
        uint256 facultyId;
        uint256 timestamp;
        string resultHash;
        address evaluator;
    }

    mapping(uint256 => EvaluationRecord) public records;
    mapping(uint256 => address[]) public approvals;
    mapping(uint256 => uint256) public approvalCount;

    event EvaluationStored(uint256 indexed facultyId, string resultHash, uint256 timestamp);
    event ApprovalAdded(uint256 indexed facultyId, address approver);

    function storeEvaluation(uint256 facultyId, string memory resultHash) public {
        records[facultyId] = EvaluationRecord({
            facultyId: facultyId,
            timestamp: block.timestamp,
            resultHash: resultHash,
            evaluator: msg.sender
        });
        emit EvaluationStored(facultyId, resultHash, block.timestamp);
    }

    function getEvaluation(uint256 facultyId) public view returns (EvaluationRecord memory) {
        return records[facultyId];
    }

    function addApproval(uint256 facultyId) public {
        approvals[facultyId].push(msg.sender);
        approvalCount[facultyId] += 1;
        emit ApprovalAdded(facultyId, msg.sender);
    }

    function getApprovalCount(uint256 facultyId) public view returns (uint256) {
        return approvalCount[facultyId];
    }
}
